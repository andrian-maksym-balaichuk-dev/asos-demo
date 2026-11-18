"""Pomocné endpointy pre dashboard a skripty (reset, stav, RPC volania, proxy na providera).

Všetky výsledky sú skutočné volania — nič nie je predpripravené.
"""
from __future__ import annotations

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


def _require_demo():
    if not config.DEMO_MODE:
        raise HTTPException(403, "Demo endpointy sú vypnuté (DEMO_MODE=false).")


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
        st = await seat_status(conn, config.DEMO_EVENT_ID, seat)
        active = await active_reservations(conn, config.DEMO_EVENT_ID, seat)
    return {
        "seat": st, "active_reservations": active, "active_count": len(active),
        "sql": ACTIVE_RESERVATIONS_SQL.replace(":event_id", "'42'").replace(":seat_id", f"'{seat}'"),
        "at": now_iso(),
    }


@router.get("/contracts/proto", response_class=PlainTextResponse, summary="gRPC kontrakt .proto")
async def proto_contract():
    from pathlib import Path
    return Path(grpc_client.__file__).with_name("inventory.proto").read_text(encoding="utf-8")


@router.get("/contracts/wsdl", response_class=PlainTextResponse, summary="SOAP kontrakt WSDL")
async def wsdl_contract():
    return wsdl_text()


@router.get("/rpc/grpc", summary="Skutočné gRPC volanie API → grpc:50051")
async def call_grpc(seat: str = Query("A7", pattern=SEAT_PATTERN),
                    delay_ms: int = Query(0, ge=0, le=5000),
                    deadline_ms: int | None = Query(None, ge=10, le=10000)):
    try:
        res = await grpc_client.check_seat(config.GRPC_TARGET, config.DEMO_EVENT_ID, seat,
                                           delay_ms, deadline_ms, correlation_id.get())
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "code": "CLIENT_ERROR", "details": str(e)}
    res["at"] = now_iso()
    res["correlation_id"] = correlation_id.get()
    res["bytes_note"] = ("Merané: veľkosť serializovanej protobuf správy (bez HTTP/2 rámcov, "
                         "bez 5 B gRPC prefixu a hlavičiek).")
    return res


@router.get("/rpc/soap", summary="Skutočné SOAP volanie API → /soap")
async def call_soap(seat: str = Query("A7", max_length=10), invalid: bool = False):
    endpoint = config.SELF_URL.rstrip("/") + "/soap"
    # invalid=True → request bez elementu seatId → SOAP Fault
    res = await soap_client.raw_check_seat(endpoint, config.DEMO_EVENT_ID, None if invalid else seat,
                                           correlation_id.get())
    res["at"] = now_iso()
    res["correlation_id"] = correlation_id.get()
    res["bytes_note"] = "Merané: veľkosť HTTP body (XML Envelope), bez HTTP hlavičiek."
    return res


class ProviderAction(BaseModel):
    reservation_id: str | None = None


@router.post("/provider/{action}", summary="Spusti simulovaného payment providera")
async def provider(action: str, body: ProviderAction):
    _require_demo()
    if action not in {"payment", "replay", "bad-signature", "unsigned", "stale"}:
        raise HTTPException(404, "Neznáma akcia providera")
    payload = {"correlation_id": correlation_id.get()}
    if action != "replay":
        if not body.reservation_id:
            raise HTTPException(422, "Chýba reservation_id — najprv vytvor PENDING rezerváciu.")
        payload["reservation_id"] = body.reservation_id
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{config.PROVIDER_URL}/simulate/{action}", json=payload)
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.json().get("detail", resp.text))
    return {**resp.json(), "at": now_iso(), "correlation_id": correlation_id.get()}


@router.get("/ws/clients", summary="Aktuálne pripojení WebSocket klienti")
async def ws_clients():
    return {"clients": manager.client_names()}


@router.get("/webhook/rejected", summary="Posledné odmietnuté webhooky (len v pamäti, nie v DB)")
async def webhook_rejected():
    return {"rejected": list(rejected_attempts)}
