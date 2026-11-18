"""Spoločné doménové dotazy — používa ich REST, SOAP aj gRPC (jedna zdrojová pravda)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


# ════════════════════════════════════════════════════════════════════════
# 1. SQL dotazy (parametrizované)
#    Aktívna rezervácia = PENDING alebo CONFIRMED. Sedadlo bez nej je FREE.
# ════════════════════════════════════════════════════════════════════════

SEAT_STATUS_SQL = """
SELECT s.event_id, s.seat_id, r.id AS reservation_id, r.status AS reservation_status
FROM seats s
LEFT JOIN reservations r
  ON r.event_id = s.event_id AND r.seat_id = s.seat_id AND r.status IN ('PENDING', 'CONFIRMED')
WHERE s.event_id = :event_id AND s.seat_id = :seat_id
"""

# Tento text sa zobrazuje aj v dashboarde (GET /demo/state → "sql")
ACTIVE_RESERVATIONS_SQL = (
    "SELECT id, buyer_id, status, created_at FROM reservations "
    "WHERE event_id = :event_id AND seat_id = :seat_id AND status IN ('PENDING', 'CONFIRMED')"
)

RESERVATION_BY_ID_SQL = """
SELECT id, event_id, seat_id, buyer_id, status, created_at, updated_at
FROM reservations
WHERE id = :id
"""


# ════════════════════════════════════════════════════════════════════════
# 2. Dotazy
# ════════════════════════════════════════════════════════════════════════

async def seat_status(conn: AsyncConnection, event_id: str, seat_id: str) -> dict | None:
    """None = sedadlo neexistuje. Inak available + stav (FREE/PENDING/CONFIRMED)."""
    row = (await conn.execute(text(SEAT_STATUS_SQL), {"event_id": event_id, "seat_id": seat_id})).first()
    if row is None:
        return None
    seat = row._mapping
    status = seat["reservation_status"] or "FREE"
    return {
        "event_id": seat["event_id"],
        "seat_id": seat["seat_id"],
        "available": status == "FREE",
        "status": status,
        "reservation_id": seat["reservation_id"],
    }


async def active_reservations(conn: AsyncConnection, event_id: str, seat_id: str) -> list[dict]:
    """Invariant z UNIQUE indexu: zoznam má vždy najviac 1 prvok."""
    rows = await conn.execute(text(ACTIVE_RESERVATIONS_SQL), {"event_id": event_id, "seat_id": seat_id})
    return [
        {**dict(row._mapping), "created_at": row._mapping["created_at"].isoformat()} for row in rows
    ]


async def get_reservation(conn: AsyncConnection, reservation_id: str) -> dict | None:
    row = (await conn.execute(text(RESERVATION_BY_ID_SQL), {"id": reservation_id})).first()
    return serialize_reservation(dict(row._mapping)) if row else None


# ════════════════════════════════════════════════════════════════════════
# 3. Serializácia — jeden JSON tvar rezervácie pre REST, webhook aj WebSocket
# ════════════════════════════════════════════════════════════════════════

def serialize_reservation(row: dict) -> dict:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "seat_id": row["seat_id"],
        "buyer_id": row["buyer_id"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }
