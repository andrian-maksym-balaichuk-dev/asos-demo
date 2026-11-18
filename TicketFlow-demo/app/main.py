"""TicketFlow API Showcase — FastAPI aplikácia (REST, SOAP, GraphQL, webhook, WebSocket, dashboard).

Beží v JEDNOM Uvicorn procese (WebSocket spojenia sú v pamäti procesu).
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.common import correlation_id, new_correlation_id, problem
from app.data.db import engine, ping
from app.data.seed import ensure_seeded
from app.graphql.endpoint import router as graphql_router
from app.routes.demo import router as demo_router
from app.routes.rest import router as rest_router
from app.webhook.receiver import router as webhook_router
from app.websocket.manager import router as ws_router
from soap_service.server import router as soap_router

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


# ════════════════════════════════════════════════════════════════════════
# 1. Logovanie — každý riadok nesie correlation ID aktuálneho requestu
# ════════════════════════════════════════════════════════════════════════

class _CidFilter(logging.Filter):
    def filter(self, record):
        record.cid = correlation_id.get()
        return True


_handler = logging.StreamHandler()
_handler.addFilter(_CidFilter())
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(cid)s] %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])
log = logging.getLogger("ticketflow")


# ════════════════════════════════════════════════════════════════════════
# 2. Štart aplikácie
# ════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(_: FastAPI):
    # bez secretu by sa nedali overiť webhooky → radšej vôbec neštartuj
    if not config.WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_SECRET nie je nastavený (pozri .env.example)")
    await ensure_seeded()
    await ping()  # zahreje pool — inicializačné dotazy dialektu nebudú v meranom scope
    log.info("TicketFlow API pripravené")
    yield
    await engine.dispose()


app = FastAPI(
    title="TicketFlow API Showcase",
    version="1.0.0",
    description=("Demo k prezentácii **Typy API**: REST + OpenAPI, SOAP/WSDL, gRPC, GraphQL, "
                 "webhooky a WebSocket nad jednou doménou — koncert 42, miesto A7.\n\n"
                 "Chyby sú vo formáte RFC 9457 `application/problem+json`. "
                 "Každá odpoveď má hlavičku `X-Correlation-ID`."),
    lifespan=lifespan,
    docs_url=None,
)


# ════════════════════════════════════════════════════════════════════════
# 3. Spoločné správanie všetkých requestov
# ════════════════════════════════════════════════════════════════════════

@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    # Prevezmi X-Correlation-ID od klienta (ak je platné), inak vygeneruj nové
    cid = new_correlation_id(request.headers.get("X-Correlation-ID"))
    token = correlation_id.set(cid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        correlation_id.reset(token)

    response.headers["X-Correlation-ID"] = cid
    if not request.url.path.startswith(("/static", "/health")):
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info("%s %s → %s (%.1f ms) [%s]", request.method, request.url.path, response.status_code,
                 elapsed_ms, cid)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    # Chyby validácie tiež ako problem+json — jeden formát chýb pre celé API
    errors = [{"loc": list(error.get("loc", [])), "msg": error.get("msg")} for error in exc.errors()]
    return problem(422, "VALIDATION_ERROR", "Neplatná požiadavka",
                   "Požiadavka nespĺňa schému (pozri errors).", errors=errors)


# ════════════════════════════════════════════════════════════════════════
# 4. Health checky
# ════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["Prevádzka"])
async def health():
    await ping()
    return {"status": "ok", "service": "api"}


@app.get("/health/deps", tags=["Prevádzka"], summary="Stav všetkých závislostí")
async def health_deps():
    from grpc_service.client import health_check

    async def check_db():
        await ping()
        return "ok"

    async def check_provider():
        async with httpx.AsyncClient(timeout=2.0) as http:
            return (await http.get(f"{config.PROVIDER_URL}/health")).json()["status"]

    deps = {
        "db": await _probe(check_db()),
        "grpc": await _probe(health_check(config.GRPC_TARGET)),
        "provider": await _probe(check_provider()),
    }
    ok = deps["db"] == "ok" and deps["grpc"] == "SERVING" and deps["provider"] == "ok"
    return JSONResponse({"ok": ok, **deps}, status_code=200 if ok else 503)


async def _probe(check) -> str:
    """Vráti výsledok kontroly; pri chybe len názov výnimky (žiadne detaily von)."""
    try:
        return await check
    except Exception as exc:  # noqa: BLE001
        return f"FAIL: {exc.__class__.__name__}"


# ════════════════════════════════════════════════════════════════════════
# 5. Routery jednotlivých typov API
# ════════════════════════════════════════════════════════════════════════

app.include_router(rest_router)       # Demo A — REST
app.include_router(soap_router)       # Demo B — SOAP
app.include_router(graphql_router)    # Demo C — GraphQL
app.include_router(webhook_router)    # Demo D — Webhook
app.include_router(ws_router)         # WebSocket notifikácie
app.include_router(demo_router)       # ovládanie dema


# ════════════════════════════════════════════════════════════════════════
# 6. Dashboard a Swagger UI
# ════════════════════════════════════════════════════════════════════════

@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    # Lokálne súbory, ak sú stiahnuté (prezentácia bez internetu), inak CDN
    vendor = FRONTEND / "vendor"
    has_local = (vendor / "swagger-ui-bundle.js").exists() and (vendor / "swagger-ui.css").exists()
    base = "/static/vendor" if has_local else "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14"
    return get_swagger_ui_html(openapi_url="/openapi.json", title="TicketFlow — Swagger UI",
                               swagger_js_url=f"{base}/swagger-ui-bundle.js",
                               swagger_css_url=f"{base}/swagger-ui.css",
                               swagger_favicon_url="/static/favicon.svg")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(FRONTEND / "index.html")
