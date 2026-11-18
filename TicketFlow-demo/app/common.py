"""Spoločné pomôcky: correlation ID, chybové odpovede RFC 9457 (problem+json), čas."""
from __future__ import annotations

import contextvars
import re
import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")
_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_correlation_id(incoming: str | None) -> str:
    if incoming and _CID_RE.match(incoming):
        return incoming
    return "cid-" + uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def problem(status: int, code: str, title: str, detail: str, **extra) -> JSONResponse:
    body = {
        "type": f"https://ticketflow.local/problems/{code.lower()}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "correlation_id": correlation_id.get(),
        "timestamp": now_iso(),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json")
