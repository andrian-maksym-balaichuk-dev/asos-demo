"""Podpis webhookov — zdieľaný protokol medzi providerom a príjemcom.

Hlavička:  TicketFlow-Signature: t=<unix_timestamp>,v1=<hex HMAC-SHA256>
Podpisuje sa:  f"{t}." + RAW BODY (presne prijaté bajty, nie re-serializovaný JSON).
Príjemca: konštantné porovnanie (hmac.compare_digest) + okno čerstvosti (replay ochrana).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

SIGNATURE_HEADER = "TicketFlow-Signature"


def compute_signature(secret: bytes, timestamp: int, raw_body: bytes) -> str:
    return hmac.new(secret, f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()


def build_header(secret: bytes, raw_body: bytes, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},v1={compute_signature(secret, ts, raw_body)}"


@dataclass
class Verification:
    ok: bool
    reason: str          # OK | MISSING_SIGNATURE | MALFORMED_SIGNATURE | STALE_TIMESTAMP | INVALID_SIGNATURE
    timestamp: int | None = None


def verify(secret: bytes, raw_body: bytes, header: str | None, tolerance_s: int,
           now: int | None = None) -> Verification:
    if not header:
        return Verification(False, "MISSING_SIGNATURE")
    ts, sigs = None, []
    for part in header.split(","):
        k, _, v = part.strip().partition("=")
        if k == "t" and v.isdigit():
            ts = int(v)
        elif k == "v1" and v:
            sigs.append(v)
    if ts is None or not sigs:
        return Verification(False, "MALFORMED_SIGNATURE")
    now = int(time.time()) if now is None else now
    if abs(now - ts) > tolerance_s:
        return Verification(False, "STALE_TIMESTAMP", ts)
    expected = compute_signature(secret, ts, raw_body)
    if any(hmac.compare_digest(expected, s) for s in sigs):
        return Verification(True, "OK", ts)
    return Verification(False, "INVALID_SIGNATURE", ts)
