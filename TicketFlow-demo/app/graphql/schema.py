"""Demo C — GraphQL: N+1 vs. DataLoader na skutočnej PostgreSQL databáze.

Meraná query:
    { event(id: "42") { seats(limit: 100) { id price { amount currency } } } }

Dátový model a čo sa naozaj deje:
* `event(id)` nevolá DB — vracia referenciu; skalárne polia (name, venue) sa
  načítajú LEN ak ich query vyžaduje (a uvidíš to v SQL logu).
* `seats(limit)` = 1 SQL dotaz na tabuľku seats.
* `price` v režime NAIVE = 1 SQL dotaz na každé sedadlo → 100 dotazov.  Spolu 101.
* `price` v režime BATCH = request-scoped DataLoader → 1 dotaz `WHERE seat_id IN (...)`. Spolu 2.

Počet sa číta z SQLAlchemy event hooku (app/data/db.py) — nie je nikde zadaný ručne.

Ochrana:
* `limit` max 100 (inak chyba), QueryDepthLimiter (max hĺbka 6).
* `internalCost` vyžaduje rolu admin (hlavička X-Demo-Role: admin — iba demo,
  v produkcii by rola pochádzala z overeného tokenu).
* DataLoader sa vytvára NOVÝ pre každý request → cache neuniká medzi používateľmi.
* V produkcii navyše: limity komplexity/nákladov query, persisted queries, timeouty.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import strawberry
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection
from strawberry.dataloader import DataLoader
from strawberry.extensions import QueryDepthLimiter
from strawberry.types import Info

from app.config import GRAPHQL_MAX_LIMIT

PRICE_ONE_SQL = text(
    "SELECT seat_id, amount_cents, currency, internal_cost_cents FROM prices "
    "WHERE event_id = :event_id AND seat_id = :seat_id")
PRICE_BATCH_SQL = text(
    "SELECT seat_id, amount_cents, currency, internal_cost_cents FROM prices "
    "WHERE event_id = :event_id AND seat_id IN :seat_ids").bindparams(bindparam("seat_ids", expanding=True))
SEATS_SQL = text(
    "SELECT seat_id, row_label, seat_number FROM seats WHERE event_id = :event_id "
    "ORDER BY row_label, seat_number LIMIT :limit")
EVENT_SQL = text("SELECT id, name, venue, starts_at FROM events WHERE id = :event_id")


@dataclass
class GQLContext:
    conn: AsyncConnection
    mode: str                 # "naive" | "batch"
    role: str                 # "public" | "admin"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    price_loader: DataLoader | None = None
    event_cache: dict = field(default_factory=dict)

    async def fetch(self, stmt, params: dict) -> list:
        # jedno DB spojenie na request → príkazy serializujeme
        async with self.lock:
            return (await self.conn.execute(stmt, params)).all()


def build_context(conn: AsyncConnection, mode: str, role: str) -> GQLContext:
    ctx = GQLContext(conn=conn, mode=mode, role=role)

    async def load_prices(keys: list[tuple[str, str]]) -> list:
        by_event: dict[str, list[str]] = {}
        for event_id, seat_id in keys:
            by_event.setdefault(event_id, []).append(seat_id)
        found = {}
        for event_id, seat_ids in by_event.items():
            for r in await ctx.fetch(PRICE_BATCH_SQL, {"event_id": event_id, "seat_ids": seat_ids}):
                found[(event_id, r.seat_id)] = r
        return [found.get(k) for k in keys]

    ctx.price_loader = DataLoader(load_fn=load_prices, max_batch_size=GRAPHQL_MAX_LIMIT)
    return ctx


@strawberry.type(description="Cena sedadla")
class Price:
    amount: float = strawberry.field(description="Suma v EUR")
    currency: str
    internal_cost_cents: strawberry.Private[int]

    @strawberry.field(description="Interný náklad v EUR — iba pre rolu admin")
    def internal_cost(self, info: Info) -> float:
        if info.context.role != "admin":
            raise PermissionError("Prístup zamietnutý: pole internalCost vyžaduje rolu admin.")
        return self.internal_cost_cents / 100


def _price(row) -> Price | None:
    if row is None:
        return None
    return Price(amount=row.amount_cents / 100, currency=row.currency.strip(),
                 internal_cost_cents=row.internal_cost_cents)


@strawberry.type(description="Sedadlo")
class Seat:
    id: strawberry.ID
    row: str
    number: int
    event_id: strawberry.Private[str]

    @strawberry.field(description="Cena — naivne 1 SQL na sedadlo, alebo cez DataLoader dávkovo")
    async def price(self, info: Info) -> Price | None:
        ctx: GQLContext = info.context
        if ctx.mode == "naive":
            rows = await ctx.fetch(PRICE_ONE_SQL, {"event_id": self.event_id, "seat_id": str(self.id)})
            return _price(rows[0] if rows else None)
        return _price(await ctx.price_loader.load((self.event_id, str(self.id))))


@strawberry.type(description="Udalosť (koncert)")
class Event:
    id: strawberry.ID

    async def _row(self, info: Info):
        ctx: GQLContext = info.context
        key = str(self.id)
        if key not in ctx.event_cache:
            rows = await ctx.fetch(EVENT_SQL, {"event_id": key})
            ctx.event_cache[key] = rows[0] if rows else None
        return ctx.event_cache[key]

    @strawberry.field
    async def name(self, info: Info) -> str | None:
        row = await self._row(info)
        return row.name if row else None

    @strawberry.field
    async def venue(self, info: Info) -> str | None:
        row = await self._row(info)
        return row.venue if row else None

    @strawberry.field(description=f"Sedadlá udalosti, limit 1–{GRAPHQL_MAX_LIMIT}")
    async def seats(self, info: Info, limit: int = 10) -> list[Seat]:
        if not 1 <= limit <= GRAPHQL_MAX_LIMIT:
            raise ValueError(f"limit musí byť 1–{GRAPHQL_MAX_LIMIT} (dostal som {limit}). "
                             "Ochrana proti drahým query.")
        rows = await info.context.fetch(SEATS_SQL, {"event_id": str(self.id), "limit": limit})
        return [Seat(id=strawberry.ID(r.seat_id), row=r.row_label, number=r.seat_number,
                     event_id=str(self.id)) for r in rows]


@strawberry.type
class Query:
    @strawberry.field(description="Referencia na udalosť; samotné volanie nerobí SQL dotaz")
    def event(self, id: strawberry.ID) -> Event:
        return Event(id=id)


schema = strawberry.Schema(query=Query, extensions=[QueryDepthLimiter(max_depth=6)])

DEMO_QUERY = '{ event(id: "42") { seats(limit: 100) { id price { amount currency } } } }'
