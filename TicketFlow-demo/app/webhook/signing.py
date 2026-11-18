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


# ════════════════════════════════════════════════════════════════════════
# 1. Strana providera — vytvorenie podpisu
# ════════════════════════════════════════════════════════════════════════

def compute_signature(secret: bytes, timestamp: int, raw_body: bytes) -> str:
    # timestamp je súčasťou podpísaných dát → útočník ho nemôže posunúť
    return hmac.new(secret, f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()


def build_header(secret: bytes, raw_body: bytes, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},v1={compute_signature(secret, ts, raw_body)}"


# ════════════════════════════════════════════════════════════════════════
# 2. Strana príjemcu — overenie podpisu
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Verification:
    ok: bool
    reason: str          # OK | MISSING_SIGNATURE | MALFORMED_SIGNATURE | STALE_TIMESTAMP | INVALID_SIGNATURE
    timestamp: int | None = None


def verify(secret: bytes, raw_body: bytes, header: str | None, tolerance_s: int,
           now: int | None = None) -> Verification:
    # 1. hlavička musí existovať
    if not header:
        return Verification(False, "MISSING_SIGNATURE")

    # 2. rozober "t=...,v1=..." (v1 môže byť viac — rotácia secretu)
    timestamp, signatures = _parse_header(header)
    if timestamp is None or not signatures:
        return Verification(False, "MALFORMED_SIGNATURE")

    # 3. okno čerstvosti — starý, inak platný request je replay
    now = int(time.time()) if now is None else now
    if abs(now - timestamp) > tolerance_s:
        return Verification(False, "STALE_TIMESTAMP", timestamp)

    # 4. konštantné porovnanie — čas odpovede neprezradí, koľko znakov sedí
    expected = compute_signature(secret, timestamp, raw_body)
    if any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        return Verification(True, "OK", timestamp)
    return Verification(False, "INVALID_SIGNATURE", timestamp)


def _parse_header(header: str) -> tuple[int | None, list[str]]:
    timestamp, signatures = None, []
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "t" and value.isdigit():
            timestamp = int(value)
        elif name == "v1" and value:
            signatures.append(value)
    return timestamp, signatures
