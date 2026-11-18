"""Spoločné pomôcky: correlation ID, čas a chybové odpovede RFC 9457 (problem+json)."""
from __future__ import annotations

import contextvars
import re
import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse


# ════════════════════════════════════════════════════════════════════════
# 1. Correlation ID — jedno ID na request, viditeľné v logoch aj v odpovediach
# ════════════════════════════════════════════════════════════════════════

# ContextVar: každý async request má vlastnú hodnotu, aj keď bežia súbežne
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")
_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_correlation_id(incoming: str | None) -> str:
    # ID od klienta prevezmeme len v bezpečnom tvare (nič nepríde do logov neočistené)
    if incoming and _CID_RE.match(incoming):
        return incoming
    return "cid-" + uuid.uuid4().hex[:12]


# ════════════════════════════════════════════════════════════════════════
# 2. Čas
# ════════════════════════════════════════════════════════════════════════

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ════════════════════════════════════════════════════════════════════════
# 3. Chybová odpoveď RFC 9457 — rovnaký tvar pre všetky HTTP chyby v API
# ════════════════════════════════════════════════════════════════════════

def problem(status: int, code: str, title: str, detail: str, **extra) -> JSONResponse:
    body = {
        "type": f"https://ticketflow.local/problems/{code.lower()}",
        "title": title,
        "status": status,
        "code": code,                       # strojovo čitateľný kód, napr. SEAT_TAKEN
        "detail": detail,                   # vysvetlenie pre človeka
        "correlation_id": correlation_id.get(),
        "timestamp": now_iso(),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json")
