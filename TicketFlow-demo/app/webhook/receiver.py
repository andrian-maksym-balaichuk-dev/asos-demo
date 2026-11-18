"""Demo D — príjemca webhookov. Poradie krokov je bezpečnostne podstatné:

1. Načítaj RAW body (max 64 kB).
2. Over podpis HMAC-SHA256 konštantným porovnaním + okno čerstvosti.
   → Neplatné: 400/401 a databáza sa NEDOTKNE (žiadny INSERT ani UPDATE).
3. Až potom parsuj JSON a validuj polia.
4. V JEDNEJ transakcii: INSERT event_id do processed_webhook_events
   (ON CONFLICT DO NOTHING = deduplikácia) a zmena PENDING → CONFIRMED.
5. Až PO commite pošli WebSocket notifikáciu.

Bez transactional outboxu: ak by proces spadol medzi commitom a broadcastom,
klienti zmenu uvidia po reconnecte cez snapshot GET /reservations/{id}.
"""
from __future__ import annotations

import json
import logging
import re
from collections import deque

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import config
from app.common import correlation_id, now_iso, problem
from app.data.db import engine
from app.data.queries import serialize_reservation
from app.webhook import signing
from app.websocket.manager import manager

log = logging.getLogger("ticketflow.webhook")
router = APIRouter(tags=["Demo D — Webhook"])

MAX_BODY = 64 * 1024
EVENT_ID_RE = re.compile(r"^evt_[A-Za-z0-9]{6,64}$")
RESERVATION_ID_RE = re.compile(r"^r-[0-9]{3,9}$")

# Odmietnuté pokusy držíme len v pamäti — zámerne NEZAPISUJEME do DB.
rejected_attempts: deque[dict] = deque(maxlen=50)

# Dôvod zamietnutia podpisu → (HTTP status, vysvetlenie pre klienta)
#   400 = klient poslal zlý formát, 401 = podpis je, ale neplatí
SIGNATURE_ERRORS = {
    "MISSING_SIGNATURE": (400, "Chýba hlavička TicketFlow-Signature."),
    "MALFORMED_SIGNATURE": (400, "Hlavička podpisu má zlý formát."),
    "STALE_TIMESTAMP": (401, f"Časová pečiatka je mimo okna ±{config.WEBHOOK_TOLERANCE_SECONDS} s (možný replay)."),
    "INVALID_SIGNATURE": (401, "HMAC podpis nesedí s raw body. Databáza sa nezmenila."),
}


# ════════════════════════════════════════════════════════════════════════
# 1. SQL dotazy
# ════════════════════════════════════════════════════════════════════════

# Deduplikácia: PRIMARY KEY event_id + ON CONFLICT DO NOTHING.
# Prázdny RETURNING = túto udalosť sme už spracovali.
SQL_MARK_EVENT_RECEIVED = text("""
    INSERT INTO processed_webhook_events (event_id, event_type, reservation_id, outcome)
    VALUES (:event_id, :event_type, :reservation_id, 'processing')
    ON CONFLICT (event_id) DO NOTHING
    RETURNING event_id
""")

SQL_FIRST_PROCESSING = text("""
    SELECT outcome, received_at
    FROM processed_webhook_events
    WHERE event_id = :event_id
""")

SQL_RESERVATION_STATUS = text("SELECT status FROM reservations WHERE id = :reservation_id")

# FOR UPDATE: zamkne riadok rezervácie až do commitu
SQL_LOCK_RESERVATION_STATUS = text("""
    SELECT status FROM reservations
    WHERE id = :reservation_id
    FOR UPDATE
""")

SQL_CONFIRM_RESERVATION = text("""
    UPDATE reservations
    SET status = 'CONFIRMED', updated_at = now()
    WHERE id = :reservation_id AND status = 'PENDING'
    RETURNING id, event_id, seat_id, buyer_id, status, created_at, updated_at
""")

SQL_SET_OUTCOME = text("""
    UPDATE processed_webhook_events
    SET outcome = :outcome
    WHERE event_id = :event_id
""")


# ════════════════════════════════════════════════════════════════════════
# 2. Endpoint
# ════════════════════════════════════════════════════════════════════════

@router.post("/webhooks/payment", summary="Príjem podpísaného webhooku od payment providera")
async def receive_payment_webhook(request: Request):
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY:
        return _reject(413, "PAYLOAD_TOO_LARGE", "Telo webhooku je väčšie ako 64 kB.")

    # 1. Over podpis nad RAW bajtmi — SKÔR, než sa dotkneme databázy alebo JSONu
    verification = signing.verify(config.WEBHOOK_SECRET.encode(), raw_body,
                                  request.headers.get(signing.SIGNATURE_HEADER),
                                  config.WEBHOOK_TOLERANCE_SECONDS)
    if not verification.ok:
        status, detail = SIGNATURE_ERRORS[verification.reason]
        return _reject(status, verification.reason, detail)

    # 2. Parsuj a validuj JSON (podpis sedí, ale obsahu ešte neveríme naslepo)
    parsed = _parse_event(raw_body)
    if isinstance(parsed, JSONResponse):
        return parsed
    event_id, event_type, reservation_id = parsed

    # 3. Deduplikácia + PENDING → CONFIRMED v JEDNEJ transakcii
    async with engine.begin() as conn:
        first_time = (await conn.execute(SQL_MARK_EVENT_RECEIVED, {
            "event_id": event_id, "event_type": event_type, "reservation_id": reservation_id,
        })).first()
        if first_time is None:
            return await _duplicate_response(conn, event_id, reservation_id)

        status_before, confirmed, outcome = await _apply_payment_event(conn, event_type, reservation_id)
        await conn.execute(SQL_SET_OUTCOME, {"outcome": outcome, "event_id": event_id})
    status_after = confirmed["status"] if confirmed else status_before

    # 4. Transakcia je COMMITnutá → až teraz WebSocket
    delivered = None
    if confirmed:
        delivered = await manager.broadcast({
            "type": "reservation.confirmed", "reservation": confirmed,
            "webhook_event_id": event_id, "correlation_id": correlation_id.get()})

    log.info("webhook %s spracovaný: %s", event_id, outcome)
    return JSONResponse({
        "result": "PROCESSED", "outcome": outcome, "event_id": event_id, "reservation_id": reservation_id,
        "status_before": status_before, "status_after": status_after, "signature": "VALID",
        "websocket_deliveries": delivered, "correlation_id": correlation_id.get(),
    })


# ════════════════════════════════════════════════════════════════════════
# 3. Pomocné kroky
# ════════════════════════════════════════════════════════════════════════

def _reject(status: int, reason: str, detail: str):
    rejected_attempts.appendleft({"at": now_iso(), "reason": reason, "correlation_id": correlation_id.get()})
    log.warning("webhook odmietnutý: %s", reason)  # nikdy nelogujeme secret ani podpis
    return problem(status, reason, "Webhook odmietnutý", detail, db_changed=False)


def _parse_event(raw_body: bytes):
    """Vráti (event_id, event_type, reservation_id), alebo hotovú 400 odpoveď."""
    try:
        event = json.loads(raw_body)
        event_id = event["id"]
        event_type = event["type"]
        reservation_id = event["data"]["reservation_id"]
    except (ValueError, KeyError, TypeError):
        return _reject(400, "INVALID_PAYLOAD", "Podpis sedí, ale JSON nemá povinné polia id/type/data.reservation_id.")
    if not (isinstance(event_id, str) and EVENT_ID_RE.match(event_id)
            and isinstance(reservation_id, str) and RESERVATION_ID_RE.match(reservation_id)):
        return _reject(400, "INVALID_PAYLOAD", "Neplatný formát event id alebo reservation_id.")
    return event_id, event_type, reservation_id


async def _duplicate_response(conn, event_id: str, reservation_id: str) -> JSONResponse:
    """Duplikát je pre providera úspech (200) — inak by ho posielal donekonečna."""
    first = (await conn.execute(SQL_FIRST_PROCESSING, {"event_id": event_id})).first()
    current = (await conn.execute(SQL_RESERVATION_STATUS, {"reservation_id": reservation_id})).scalar()
    log.info("duplicitný webhook %s — bez zmeny stavu", event_id)
    return JSONResponse({
        "result": "DUPLICATE_IGNORED", "event_id": event_id, "reservation_id": reservation_id,
        "status_before": current, "status_after": current,
        "first_processed_at": first.received_at.isoformat(), "first_outcome": first.outcome,
        "detail": "Udalosť už bola spracovaná. Prijatá bezpečne (200), stav sa nezmenil.",
        "correlation_id": correlation_id.get(),
    })


async def _apply_payment_event(conn, event_type: str, reservation_id: str):
    """Vráti (stav pred, potvrdená rezervácia alebo None, outcome)."""
    status_before = (await conn.execute(SQL_LOCK_RESERVATION_STATUS,
                                        {"reservation_id": reservation_id})).scalar()

    if event_type == "payment.succeeded" and status_before == "PENDING":
        row = (await conn.execute(SQL_CONFIRM_RESERVATION, {"reservation_id": reservation_id})).first()
        return status_before, serialize_reservation(dict(row._mapping)), "CONFIRMED"
    if status_before is None:
        return status_before, None, "RESERVATION_NOT_FOUND"
    if event_type != "payment.succeeded":
        return status_before, None, "IGNORED_EVENT_TYPE"
    return status_before, None, f"IGNORED_STATUS_{status_before}"
