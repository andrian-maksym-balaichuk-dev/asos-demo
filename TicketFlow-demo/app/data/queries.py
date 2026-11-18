"""Spoločné doménové dotazy — používa ich REST, SOAP aj gRPC (jedna zdrojová pravda)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SEAT_STATUS_SQL = """
SELECT s.event_id, s.seat_id, r.id AS reservation_id, r.status AS reservation_status
FROM seats s
LEFT JOIN reservations r
  ON r.event_id = s.event_id AND r.seat_id = s.seat_id AND r.status IN ('PENDING', 'CONFIRMED')
WHERE s.event_id = :event_id AND s.seat_id = :seat_id
"""

ACTIVE_RESERVATIONS_SQL = (
    "SELECT id, buyer_id, status, created_at FROM reservations "
    "WHERE event_id = :event_id AND seat_id = :seat_id AND status IN ('PENDING', 'CONFIRMED')"
)


async def seat_status(conn: AsyncConnection, event_id: str, seat_id: str) -> dict | None:
    """None = sedadlo neexistuje. Inak available + stav (FREE/PENDING/CONFIRMED)."""
    row = (await conn.execute(text(SEAT_STATUS_SQL), {"event_id": event_id, "seat_id": seat_id})).first()
    if row is None:
        return None
    m = row._mapping
    status = m["reservation_status"] or "FREE"
    return {
        "event_id": m["event_id"],
        "seat_id": m["seat_id"],
        "available": status == "FREE",
        "status": status,
        "reservation_id": m["reservation_id"],
    }


async def active_reservations(conn: AsyncConnection, event_id: str, seat_id: str) -> list[dict]:
    rows = await conn.execute(text(ACTIVE_RESERVATIONS_SQL), {"event_id": event_id, "seat_id": seat_id})
    return [
        {**dict(r._mapping), "created_at": r._mapping["created_at"].isoformat()} for r in rows
    ]


async def get_reservation(conn: AsyncConnection, reservation_id: str) -> dict | None:
    row = (await conn.execute(
        text("SELECT id, event_id, seat_id, buyer_id, status, created_at, updated_at "
             "FROM reservations WHERE id = :id"),
        {"id": reservation_id},
    )).first()
    return serialize_reservation(dict(row._mapping)) if row else None


def serialize_reservation(r: dict) -> dict:
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "seat_id": r["seat_id"],
        "buyer_id": r["buyer_id"],
        "status": r["status"],
        "created_at": r["created_at"].isoformat(),
        "updated_at": r["updated_at"].isoformat(),
    }
