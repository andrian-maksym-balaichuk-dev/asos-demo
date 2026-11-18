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


class _CidFilter(logging.Filter):
    def filter(self, record):
        record.cid = correlation_id.get()
        return True


_handler = logging.StreamHandler()
_handler.addFilter(_CidFilter())
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(cid)s] %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])
log = logging.getLogger("ticketflow")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
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


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    cid = new_correlation_id(request.headers.get("X-Correlation-ID"))
    token = correlation_id.set(cid)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        correlation_id.reset(token)
    response.headers["X-Correlation-ID"] = cid
    if not request.url.path.startswith(("/static", "/health")):
        log.info("%s %s → %s (%.1f ms) [%s]", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t0) * 1000, cid)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
    return problem(422, "VALIDATION_ERROR", "Neplatná požiadavka",
                   "Požiadavka nespĺňa schému (pozri errors).", errors=errors)


@app.get("/health", tags=["Prevádzka"])
async def health():
    await ping()
    return {"status": "ok", "service": "api"}


@app.get("/health/deps", tags=["Prevádzka"], summary="Stav všetkých závislostí")
async def health_deps():
    from grpc_service.client import health_check
    out = {}
    try:
        await ping()
        out["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        out["db"] = f"FAIL: {e.__class__.__name__}"
    try:
        out["grpc"] = await health_check(config.GRPC_TARGET)
    except Exception as e:  # noqa: BLE001
        out["grpc"] = f"FAIL: {e.__class__.__name__}"
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            out["provider"] = (await c.get(f"{config.PROVIDER_URL}/health")).json()["status"]
    except Exception as e:  # noqa: BLE001
        out["provider"] = f"FAIL: {e.__class__.__name__}"
    ok = out["db"] == "ok" and out["grpc"] == "SERVING" and out["provider"] == "ok"
    return JSONResponse({"ok": ok, **out}, status_code=200 if ok else 503)


app.include_router(rest_router)
app.include_router(soap_router)
app.include_router(graphql_router)
app.include_router(webhook_router)
app.include_router(ws_router)
app.include_router(demo_router)


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    vendor = FRONTEND / "vendor"
    local = (vendor / "swagger-ui-bundle.js").exists() and (vendor / "swagger-ui.css").exists()
    base = "/static/vendor" if local else "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14"
    return get_swagger_ui_html(openapi_url="/openapi.json", title="TicketFlow — Swagger UI",
                               swagger_js_url=f"{base}/swagger-ui-bundle.js",
                               swagger_css_url=f"{base}/swagger-ui.css",
                               swagger_favicon_url="/static/favicon.svg")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(FRONTEND / "index.html")
