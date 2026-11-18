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
EVENT = {
    "id": "42",
    "name": "TicketFlow Live — Koncert 42",
    "venue": "Demo hala, Bratislava",
    "starts_at": "2026-12-12T19:00:00+01:00",
}


def price_for_row(row: str) -> tuple[int, int]:
    """(cena pre zákazníka, interný náklad) v centoch."""
    if row in "ABC":
        return 5900, 3100
    if row in "DEFG":
        return 4500, 2400
    return 3200, 1700


async def create_schema(conn: AsyncConnection) -> None:
    for stmt in SCHEMA_SQL:
        await conn.execute(text(stmt))


async def reset_and_seed(conn: AsyncConnection) -> dict:
    await conn.execute(text(
        "TRUNCATE processed_webhook_events, idempotency_keys, reservations, prices, seats, events"
    ))
    await conn.execute(text("ALTER SEQUENCE reservation_seq RESTART WITH 1"))
    await conn.execute(
        text("INSERT INTO events (id, name, venue, starts_at) VALUES (:id, :name, :venue, CAST(:starts_at AS timestamptz))"),
        EVENT,
    )
    seats, prices = [], []
    for row in ROWS:
        amount, cost = price_for_row(row)
        for n in range(1, 11):
            sid = f"{row}{n}"
            seats.append({"e": EVENT["id"], "s": sid, "r": row, "n": n})
            prices.append({"e": EVENT["id"], "s": sid, "a": amount, "c": cost})
    await conn.execute(
        text("INSERT INTO seats (event_id, seat_id, row_label, seat_number) VALUES (:e, :s, :r, :n)"), seats
    )
    await conn.execute(
        text("INSERT INTO prices (event_id, seat_id, amount_cents, currency, internal_cost_cents) "
             "VALUES (:e, :s, :a, 'EUR', :c)"),
        prices,
    )
    return {"event_id": EVENT["id"], "seats": len(seats), "prices": len(prices)}


async def ensure_seeded() -> None:
    """Pri štarte: vytvor schému; ak chýba event 42, naseeduj."""
    async with engine.begin() as conn:
        # advisory lock: bezpečné aj keby sa schéma vytvárala z viacerých procesov
        await conn.execute(text("SELECT pg_advisory_xact_lock(4242)"))
        await create_schema(conn)
        exists = (await conn.execute(text("SELECT 1 FROM events WHERE id = '42'"))).first()
        if not exists:
            await reset_and_seed(conn)


async def _main() -> None:
    async with engine.begin() as conn:
        await create_schema(conn)
        print(await reset_and_seed(conn))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
