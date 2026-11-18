"""Simulovaný payment provider (samostatná služba, port 8002).

Naozaj podpisuje RAW body (HMAC) a posiela HTTP POST na príjemcu webhookov.
Žiadna reálna platba, žiadne externé volania. Tajomstvo sa nikdy neloguje.

POST /simulate/payment       {reservation_id}  nová udalosť payment.succeeded, platný podpis
POST /simulate/replay                          znovu pošle POSLEDNÚ udalosť (rovnaké event id aj body)
POST /simulate/bad-signature {reservation_id}  podpíše, potom zmení body (amount) → podpis nesedí
POST /simulate/unsigned      {reservation_id}  bez hlavičky podpisu
POST /simulate/stale         {reservation_id}  platný HMAC, ale timestamp 10 min starý

Spustenie (v kontajneri):  uvicorn provider_simulator.payment_provider:app --port 8002
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.webhook.signing import SIGNATURE_HEADER, build_header

log = logging.getLogger("provider")

SECRET = os.getenv("WEBHOOK_SECRET", "").encode()
TARGET = os.getenv("WEBHOOK_TARGET_URL", "http://localhost:8000/webhooks/payment")
if not SECRET:
    raise RuntimeError("WEBHOOK_SECRET nie je nastavený")

STALE_AGE_SECONDS = 600   # 10 minút — mimo tolerančného okna príjemcu

app = FastAPI(title="TicketFlow — simulovaný payment provider", version="1.0.0")

# Posledná odoslaná udalosť (raw bajty) pre /simulate/replay
_last: dict | None = None
# Correlation ID preposielame len ak je bezpečné (žiadne vkladanie hlavičiek)
_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


# ════════════════════════════════════════════════════════════════════════
# 1. Modely požiadaviek
# ════════════════════════════════════════════════════════════════════════

class SimRequest(BaseModel):
    reservation_id: str = Field(pattern=r"^r-[0-9]{3,9}$")
    amount_cents: int = Field(default=5900, gt=0, le=1_000_000)
    correlation_id: str | None = None


class ReplayRequest(BaseModel):
    correlation_id: str | None = None


# ════════════════════════════════════════════════════════════════════════
# 2. Pomocné funkcie: udalosť, serializácia, doručenie
# ════════════════════════════════════════════════════════════════════════

def _event(reservation_id: str, amount_cents: int) -> dict:
    return {
        "id": "evt_" + secrets.token_hex(8),
        "type": "payment.succeeded",
        "created": int(time.time()),
        "data": {"reservation_id": reservation_id, "payment_id": "pay_" + secrets.token_hex(6),
                 "amount_cents": amount_cents, "currency": "EUR"},
    }


def _to_raw(event: dict) -> bytes:
    # Podpisujú sa presne tieto bajty → kompaktný JSON bez medzier
    return json.dumps(event, separators=(",", ":")).encode()


async def _deliver(raw: bytes, signature: str | None, cid: str | None, note: str) -> dict:
    """Pošle raw body príjemcovi a vráti, čo sa odoslalo aj čo prišlo späť."""
    # 1. hlavičky
    headers = {"Content-Type": "application/json"}
    if signature:
        headers[SIGNATURE_HEADER] = signature
    if cid and _CID_RE.match(cid):
        headers["X-Correlation-ID"] = cid

    # 2. HTTP POST na príjemcu
    started_at = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0) as http:
        response = await http.post(TARGET, content=raw, headers=headers)
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)

    # 3. odpoveď príjemcu (JSON, inak text)
    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text
    return {
        "note": note,
        "sent": {"url": TARGET, "headers": headers, "raw_body": raw.decode()},
        "received": {"status": response.status_code, "body": response_body},
        "elapsed_ms": elapsed_ms,
    }


# ════════════════════════════════════════════════════════════════════════
# 3. Endpointy
# ════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "ok", "service": "provider"}


@app.post("/simulate/payment")
async def simulate_payment(req: SimRequest):
    global _last
    raw = _to_raw(_event(req.reservation_id, req.amount_cents))
    _last = {"raw": raw}
    return await _deliver(raw, build_header(SECRET, raw), req.correlation_id,
                          "Nová udalosť s platným HMAC podpisom.")


@app.post("/simulate/replay")
async def simulate_replay(req: ReplayRequest | None = None):
    if _last is None:
        raise HTTPException(409, "Zatiaľ nebola odoslaná žiadna udalosť na zopakovanie.")
    raw = _last["raw"]
    # Ako reálni provideri pri retry: rovnaké event id a body, nový timestamp a podpis.
    return await _deliver(raw, build_header(SECRET, raw), req.correlation_id if req else None,
                          "Opakované doručenie tej istej udalosti (rovnaké event id).")


@app.post("/simulate/bad-signature")
async def simulate_bad_signature(req: SimRequest):
    event = _event(req.reservation_id, req.amount_cents)
    signature = build_header(SECRET, _to_raw(event))
    event["data"]["amount_cents"] = 1  # útočník zmenil sumu PO podpise
    tampered_raw = _to_raw(event)
    return await _deliver(tampered_raw, signature, req.correlation_id,
                          "Body zmenené po podpísaní (amount_cents → 1). Podpis nesedí.")


@app.post("/simulate/unsigned")
async def simulate_unsigned(req: SimRequest):
    raw = _to_raw(_event(req.reservation_id, req.amount_cents))
    return await _deliver(raw, None, req.correlation_id, "Bez hlavičky TicketFlow-Signature.")


@app.post("/simulate/stale")
async def simulate_stale(req: SimRequest):
    raw = _to_raw(_event(req.reservation_id, req.amount_cents))
    stale_timestamp = int(time.time()) - STALE_AGE_SECONDS
    return await _deliver(raw, build_header(SECRET, raw, stale_timestamp), req.correlation_id,
                          "Platný HMAC, ale timestamp je 10 minút starý.")
