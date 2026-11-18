"""Pomocné endpointy pre dashboard a skripty (reset, stav, RPC volania, proxy na providera).

Všetky výsledky sú skutočné volania — nič nie je predpripravené.
"""
from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import config
from app.common import correlation_id, now_iso
from app.data.db import engine
from app.data.queries import ACTIVE_RESERVATIONS_SQL, active_reservations, seat_status
from app.data.seed import reset_and_seed
from app.webhook.receiver import rejected_attempts
from app.websocket.manager import manager
from grpc_service import client as grpc_client
from soap_service import client as soap_client
from soap_service.server import wsdl_text

router = APIRouter(prefix="/demo", tags=["Demo — ovládanie"])
SEAT_PATTERN = r"^[A-J](10|[1-9])$"
PROVIDER_ACTIONS = {"payment", "replay", "bad-signature", "unsigned", "stale"}


def _require_demo():
    # Zapisujúce demo endpointy sa dajú vypnúť (DEMO_MODE=false)
    if not config.DEMO_MODE:
        raise HTTPException(403, "Demo endpointy sú vypnuté (DEMO_MODE=false).")


def _with_meta(result: dict) -> dict:
    """Doplní čas a correlation ID — aby sa dal výsledok spárovať s logmi."""
    result["at"] = now_iso()
    result["correlation_id"] = correlation_id.get()
    return result


# ════════════════════════════════════════════════════════════════════════
# 1. Reset a stav dát
# ════════════════════════════════════════════════════════════════════════

@router.post("/reset", summary="Reset demo dát (koncert 42, 100 sedadiel, žiadne rezervácie)")
async def reset():
    _require_demo()
    async with engine.begin() as conn:
        seeded = await reset_and_seed(conn)
    rejected_attempts.clear()
    await manager.broadcast({"type": "demo.reset", "correlation_id": correlation_id.get()})
    return {"result": "RESET_OK", **seeded, "at": now_iso(), "correlation_id": correlation_id.get()}


@router.get("/state", summary="Stav sedadla + aktívne rezervácie (pre pred/po)")
async def state(seat: str = Query("A7", pattern=SEAT_PATTERN)):
    async with engine.connect() as conn:
        seat_info = await seat_status(conn, config.DEMO_EVENT_ID, seat)
        active = await active_reservations(conn, config.DEMO_EVENT_ID, seat)
    # SQL s dosadenými hodnotami je LEN na zobrazenie; vykonáva sa parametrizovaná verzia
    shown_sql = ACTIVE_RESERVATIONS_SQL.replace(":event_id", "'42'").replace(":seat_id", f"'{seat}'")
    return {
        "seat": seat_info, "active_reservations": active, "active_count": len(active),
        "sql": shown_sql,
        "at": now_iso(),
    }


# ════════════════════════════════════════════════════════════════════════
# 2. Kontrakty (.proto a WSDL) na zobrazenie v dashboarde
# ════════════════════════════════════════════════════════════════════════

@router.get("/contracts/proto", response_class=PlainTextResponse, summary="gRPC kontrakt .proto")
async def proto_contract():
    return Path(grpc_client.__file__).with_name("inventory.proto").read_text(encoding="utf-8")


@router.get("/contracts/wsdl", response_class=PlainTextResponse, summary="SOAP kontrakt WSDL")
async def wsdl_contract():
    return wsdl_text()


# ════════════════════════════════════════════════════════════════════════
# 3. RPC volania (gRPC, SOAP) — API ich volá ako skutočný klient
# ════════════════════════════════════════════════════════════════════════

@router.get("/rpc/grpc", summary="Skutočné gRPC volanie API → grpc:50051")
async def call_grpc(seat: str = Query("A7", pattern=SEAT_PATTERN),
                    delay_ms: int = Query(0, ge=0, le=5000),
                    deadline_ms: int | None = Query(None, ge=10, le=10000)):
    try:
        result = await grpc_client.check_seat(config.GRPC_TARGET, config.DEMO_EVENT_ID, seat,
                                              delay_ms, deadline_ms, correlation_id.get())
    except Exception as exc:  # noqa: BLE001 — chybu ukážeme v dashboarde, nie ako 500
        result = {"ok": False, "code": "CLIENT_ERROR", "details": str(exc)}
    _with_meta(result)
    result["bytes_note"] = ("Merané: veľkosť serializovanej protobuf správy (bez HTTP/2 rámcov, "
                            "bez 5 B gRPC prefixu a hlavičiek).")
    return result


@router.get("/rpc/soap", summary="Skutočné SOAP volanie API → /soap")
async def call_soap(seat: str = Query("A7", max_length=10), invalid: bool = False):
    endpoint = config.SELF_URL.rstrip("/") + "/soap"
    # invalid=True → request bez elementu seatId → SOAP Fault
    result = await soap_client.raw_check_seat(endpoint, config.DEMO_EVENT_ID, None if invalid else seat,
                                              correlation_id.get())
    _with_meta(result)
    result["bytes_note"] = "Merané: veľkosť HTTP body (XML Envelope), bez HTTP hlavičiek."
    return result


# ════════════════════════════════════════════════════════════════════════
# 4. Simulovaný payment provider (spúšťa webhooky pre Demo D)
# ════════════════════════════════════════════════════════════════════════

class ProviderAction(BaseModel):
    reservation_id: str | None = None


@router.post("/provider/{action}", summary="Spusti simulovaného payment providera")
async def provider(action: str, body: ProviderAction):
    _require_demo()
    if action not in PROVIDER_ACTIONS:
        raise HTTPException(404, "Neznáma akcia providera")

    payload = {"correlation_id": correlation_id.get()}
    # replay posiela znova poslednú udalosť → reservation_id nepotrebuje
    if action != "replay":
        if not body.reservation_id:
            raise HTTPException(422, "Chýba reservation_id — najprv vytvor PENDING rezerváciu.")
        payload["reservation_id"] = body.reservation_id

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{config.PROVIDER_URL}/simulate/{action}", json=payload)
    if response.status_code >= 400:
        raise HTTPException(response.status_code, response.json().get("detail", response.text))
    return {**response.json(), "at": now_iso(), "correlation_id": correlation_id.get()}


# ════════════════════════════════════════════════════════════════════════
# 5. Diagnostika pre dashboard
# ════════════════════════════════════════════════════════════════════════

@router.get("/ws/clients", summary="Aktuálne pripojení WebSocket klienti")
async def ws_clients():
    return {"clients": manager.client_names()}


@router.get("/webhook/rejected", summary="Posledné odmietnuté webhooky (len v pamäti, nie v DB)")
async def webhook_rejected():
    return {"rejected": list(rejected_attempts)}
