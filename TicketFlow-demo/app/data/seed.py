"""Deterministické demo dáta: koncert 42, 100 sedadiel (A1–J10), samostatná tabuľka cien.

Spustenie: python -m app.data.seed  (alebo POST /demo/reset)
Reset vždy vráti rovnaký stav: žiadne rezervácie, sekvencia rezervácií začína r-001.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.data.db import engine
from app.data.models import SCHEMA_SQL

ROWS = "ABCDEFGHIJ"
SEATS_PER_ROW = 10
EVENT = {
    "id": "42",
    "name": "TicketFlow Live — Koncert 42",
    "venue": "Demo hala, Bratislava",
    "starts_at": "2026-12-12T19:00:00+01:00",
}


# ════════════════════════════════════════════════════════════════════════
# 1. SQL príkazy
# ════════════════════════════════════════════════════════════════════════

SQL_TRUNCATE_ALL = text("""
    TRUNCATE processed_webhook_events, idempotency_keys, reservations, prices, seats, events
""")

# r-001 po každom resete → rovnaké ID v každom behu dema
SQL_RESTART_RESERVATION_SEQ = text("ALTER SEQUENCE reservation_seq RESTART WITH 1")

SQL_INSERT_EVENT = text("""
    INSERT INTO events (id, name, venue, starts_at)
    VALUES (:id, :name, :venue, CAST(:starts_at AS timestamptz))
""")

SQL_INSERT_SEAT = text("""
    INSERT INTO seats (event_id, seat_id, row_label, seat_number)
    VALUES (:event_id, :seat_id, :row_label, :seat_number)
""")

SQL_INSERT_PRICE = text("""
    INSERT INTO prices (event_id, seat_id, amount_cents, currency, internal_cost_cents)
    VALUES (:event_id, :seat_id, :amount_cents, 'EUR', :internal_cost_cents)
""")

# Advisory lock: bezpečné, aj keby schému vytváralo viac procesov naraz
SQL_SCHEMA_LOCK = text("SELECT pg_advisory_xact_lock(4242)")

SQL_DEMO_EVENT_EXISTS = text("SELECT 1 FROM events WHERE id = '42'")


# ════════════════════════════════════════════════════════════════════════
# 2. Dáta
# ════════════════════════════════════════════════════════════════════════

def price_for_row(row: str) -> tuple[int, int]:
    """(cena pre zákazníka, interný náklad) v centoch."""
    if row in "ABC":
        return 5900, 3100
    if row in "DEFG":
        return 4500, 2400
    return 3200, 1700


def _seat_and_price_rows() -> tuple[list[dict], list[dict]]:
    seats, prices = [], []
    for row in ROWS:
        amount, cost = price_for_row(row)
        for number in range(1, SEATS_PER_ROW + 1):
            seat_id = f"{row}{number}"
            seats.append({"event_id": EVENT["id"], "seat_id": seat_id, "row_label": row, "seat_number": number})
            prices.append({"event_id": EVENT["id"], "seat_id": seat_id,
                           "amount_cents": amount, "internal_cost_cents": cost})
    return seats, prices


# ════════════════════════════════════════════════════════════════════════
# 3. Schéma, reset a seed
# ════════════════════════════════════════════════════════════════════════

async def create_schema(conn: AsyncConnection) -> None:
    for statement in SCHEMA_SQL:
        await conn.execute(text(statement))


async def reset_and_seed(conn: AsyncConnection) -> dict:
    # 1. vymaž všetko a vráť sekvenciu na začiatok
    await conn.execute(SQL_TRUNCATE_ALL)
    await conn.execute(SQL_RESTART_RESERVATION_SEQ)

    # 2. udalosť, sedadlá a ceny (executemany = jeden príkaz pre všetky riadky)
    await conn.execute(SQL_INSERT_EVENT, EVENT)
    seats, prices = _seat_and_price_rows()
    await conn.execute(SQL_INSERT_SEAT, seats)
    await conn.execute(SQL_INSERT_PRICE, prices)

    return {"event_id": EVENT["id"], "seats": len(seats), "prices": len(prices)}


async def ensure_seeded() -> None:
    """Pri štarte: vytvor schému; ak chýba event 42, naseeduj."""
    async with engine.begin() as conn:
        await conn.execute(SQL_SCHEMA_LOCK)
        await create_schema(conn)
        exists = (await conn.execute(SQL_DEMO_EVENT_EXISTS)).first()
        if not exists:
            await reset_and_seed(conn)


async def _main() -> None:
    async with engine.begin() as conn:
        await create_schema(conn)
        print(await reset_and_seed(conn))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
