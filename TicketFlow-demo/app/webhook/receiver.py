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
_EVT_RE = re.compile(r"^evt_[A-Za-z0-9]{6,64}$")
_RES_RE = re.compile(r"^r-[0-9]{3,9}$")

# Odmietnuté pokusy držíme len v pamäti — zámerne NEZAPISUJEME do DB.
rejected_attempts: deque[dict] = deque(maxlen=50)


def _reject(status: int, reason: str, detail: str):
    rejected_attempts.appendleft({"at": now_iso(), "reason": reason, "correlation_id": correlation_id.get()})
    log.warning("webhook odmietnutý: %s", reason)  # nikdy nelogujeme secret ani podpis
    return problem(status, reason, "Webhook odmietnutý", detail, db_changed=False)


@router.post("/webhooks/payment", summary="Príjem podpísaného webhooku od payment providera")
async def receive_payment_webhook(request: Request):
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return _reject(413, "PAYLOAD_TOO_LARGE", "Telo webhooku je väčšie ako 64 kB.")

    v = signing.verify(config.WEBHOOK_SECRET.encode(), raw, request.headers.get(signing.SIGNATURE_HEADER),
                       config.WEBHOOK_TOLERANCE_SECONDS)
    if not v.ok:
        status = 400 if v.reason in ("MISSING_SIGNATURE", "MALFORMED_SIGNATURE") else 401
        detail = {
            "MISSING_SIGNATURE": "Chýba hlavička TicketFlow-Signature.",
            "MALFORMED_SIGNATURE": "Hlavička podpisu má zlý formát.",
            "STALE_TIMESTAMP": f"Časová pečiatka je mimo okna ±{config.WEBHOOK_TOLERANCE_SECONDS} s (možný replay).",
            "INVALID_SIGNATURE": "HMAC podpis nesedí s raw body. Databáza sa nezmenila.",
        }[v.reason]
        return _reject(status, v.reason, detail)

    try:
        event = json.loads(raw)
        event_id = event["id"]
        event_type = event["type"]
        reservation_id = event["data"]["reservation_id"]
    except (ValueError, KeyError, TypeError):
        return _reject(400, "INVALID_PAYLOAD", "Podpis sedí, ale JSON nemá povinné polia id/type/data.reservation_id.")
    if not (isinstance(event_id, str) and _EVT_RE.match(event_id)
            and isinstance(reservation_id, str) and _RES_RE.match(reservation_id)):
        return _reject(400, "INVALID_PAYLOAD", "Neplatný formát event id alebo reservation_id.")

    broadcast_payload = None
    async with engine.begin() as conn:
        inserted = (await conn.execute(text(
            "INSERT INTO processed_webhook_events (event_id, event_type, reservation_id, outcome) "
            "VALUES (:id, :t, :r, 'processing') ON CONFLICT (event_id) DO NOTHING RETURNING event_id"),
            {"id": event_id, "t": event_type, "r": reservation_id})).first()
        if inserted is None:
            prev = (await conn.execute(text(
                "SELECT outcome, received_at FROM processed_webhook_events WHERE event_id = :id"),
                {"id": event_id})).first()
            current = (await conn.execute(text("SELECT status FROM reservations WHERE id = :r"),
                                          {"r": reservation_id})).scalar()
            log.info("duplicitný webhook %s — bez zmeny stavu", event_id)
            return JSONResponse({
                "result": "DUPLICATE_IGNORED", "event_id": event_id, "reservation_id": reservation_id,
                "status_before": current, "status_after": current,
                "first_processed_at": prev.received_at.isoformat(), "first_outcome": prev.outcome,
                "detail": "Udalosť už bola spracovaná. Prijatá bezpečne (200), stav sa nezmenil.",
                "correlation_id": correlation_id.get(),
            })

        before = (await conn.execute(text("SELECT status FROM reservations WHERE id = :r FOR UPDATE"),
                                     {"r": reservation_id})).scalar()
        after = before
        if event_type == "payment.succeeded" and before == "PENDING":
            row = (await conn.execute(text(
                "UPDATE reservations SET status = 'CONFIRMED', updated_at = now() "
                "WHERE id = :r AND status = 'PENDING' "
                "RETURNING id, event_id, seat_id, buyer_id, status, created_at, updated_at"),
                {"r": reservation_id})).first()
            after = row.status
            outcome = "CONFIRMED"
            broadcast_payload = serialize_reservation(dict(row._mapping))
        elif before is None:
            outcome = "RESERVATION_NOT_FOUND"
        elif event_type != "payment.succeeded":
            outcome = "IGNORED_EVENT_TYPE"
        else:
            outcome = f"IGNORED_STATUS_{before}"
        await conn.execute(text("UPDATE processed_webhook_events SET outcome = :o WHERE event_id = :id"),
                           {"o": outcome, "id": event_id})
    # transakcia je COMMITnutá → až teraz WebSocket
    delivered = None
    if broadcast_payload:
        delivered = await manager.broadcast({
            "type": "reservation.confirmed", "reservation": broadcast_payload,
            "webhook_event_id": event_id, "correlation_id": correlation_id.get()})
    log.info("webhook %s spracovaný: %s", event_id, outcome)
    return JSONResponse({
        "result": "PROCESSED", "outcome": outcome, "event_id": event_id, "reservation_id": reservation_id,
        "status_before": before, "status_after": after, "signature": "VALID",
        "websocket_deliveries": delivered, "correlation_id": correlation_id.get(),
    })
