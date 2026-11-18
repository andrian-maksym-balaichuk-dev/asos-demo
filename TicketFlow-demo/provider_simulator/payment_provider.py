"""Simulovaný payment provider (samostatná služba, port 8002).

Naozaj podpisuje RAW body a posiela HTTP POST na príjemcu webhookov.
Žiadna reálna platba, žiadne externé volania.

POST /simulate/payment       {reservation_id}  nová udalosť payment.succeeded, platný podpis
POST /simulate/replay                          znovu pošle POSLEDNÚ udalosť (rovnaké event id aj body)
POST /simulate/bad-signature {reservation_id}  podpíše, potom zmení body (amount) → podpis nesedí
POST /simulate/unsigned      {reservation_id}  bez hlavičky podpisu
POST /simulate/stale         {reservation_id}  platný HMAC, ale timestamp 10 min starý
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

app = FastAPI(title="TicketFlow — simulovaný payment provider", version="1.0.0")
_last: dict | None = None
_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class SimRequest(BaseModel):
    reservation_id: str = Field(pattern=r"^r-[0-9]{3,9}$")
    amount_cents: int = Field(default=5900, gt=0, le=1_000_000)
    correlation_id: str | None = None


def _event(reservation_id: str, amount_cents: int) -> dict:
    return {
        "id": "evt_" + secrets.token_hex(8),
        "type": "payment.succeeded",
        "created": int(time.time()),
        "data": {"reservation_id": reservation_id, "payment_id": "pay_" + secrets.token_hex(6),
                 "amount_cents": amount_cents, "currency": "EUR"},
    }


async def _deliver(raw: bytes, signature: str | None, cid: str | None, note: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if signature:
        headers[SIGNATURE_HEADER] = signature
    if cid and _CID_RE.match(cid):
        headers["X-Correlation-ID"] = cid
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(TARGET, content=raw, headers=headers)
    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return {
        "note": note,
        "sent": {"url": TARGET, "headers": headers, "raw_body": raw.decode()},
        "received": {"status": resp.status_code, "body": body},
        "elapsed_ms": elapsed,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "provider"}


@app.post("/simulate/payment")
async def simulate_payment(req: SimRequest):
    global _last
    raw = json.dumps(_event(req.reservation_id, req.amount_cents), separators=(",", ":")).encode()
    _last = {"raw": raw}
    return await _deliver(raw, build_header(SECRET, raw), req.correlation_id,
                          "Nová udalosť s platným HMAC podpisom.")


class ReplayRequest(BaseModel):
    correlation_id: str | None = None


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
    raw = json.dumps(event, separators=(",", ":")).encode()
    signature = build_header(SECRET, raw)
    event["data"]["amount_cents"] = 1  # útočník zmenil sumu PO podpise
    tampered = json.dumps(event, separators=(",", ":")).encode()
    return await _deliver(tampered, signature, req.correlation_id,
                          "Body zmenené po podpísaní (amount_cents → 1). Podpis nesedí.")


@app.post("/simulate/unsigned")
async def simulate_unsigned(req: SimRequest):
    raw = json.dumps(_event(req.reservation_id, req.amount_cents), separators=(",", ":")).encode()
    return await _deliver(raw, None, req.correlation_id, "Bez hlavičky TicketFlow-Signature.")


@app.post("/simulate/stale")
async def simulate_stale(req: SimRequest):
    raw = json.dumps(_event(req.reservation_id, req.amount_cents), separators=(",", ":")).encode()
    return await _deliver(raw, build_header(SECRET, raw, int(time.time()) - 600), req.correlation_id,
                          "Platný HMAC, ale timestamp je 10 minút starý.")
