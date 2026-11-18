"""Demo C — GraphQL: problém N+1 a jeho riešenie DataLoaderom.

Query z dema:
    { event(id: "42") { seats(limit: 100) { id price { amount currency } } } }

    naivne:    1 SQL (sedadlá) + 100 SQL (cena pre každé sedadlo) = 101
    batching:  1 SQL (sedadlá) +   1 SQL (všetky ceny naraz)       =   2

Čísla nie sú nikde napísané. Počíta ich hook v app/data/db.py.
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

DEMO_QUERY = '{ event(id: "42") { seats(limit: 100) { id price { amount currency } } } }'


# ════════════════════════════════════════════════════════════════════════
# 1. SQL dotazy (parametrizované — hodnoty od klienta sa nikdy nevkladajú do textu SQL)
# ════════════════════════════════════════════════════════════════════════

SQL_SEATS = text("""
    SELECT seat_id, row_label, seat_number
    FROM seats
    WHERE event_id = :event_id
    ORDER BY row_label, seat_number
    LIMIT :limit
""")

# naivne: cena pre JEDNO sedadlo → volá sa 100×
SQL_PRICE_ONE_SEAT = text("""
    SELECT seat_id, amount_cents, currency, internal_cost_cents
    FROM prices
    WHERE event_id = :event_id AND seat_id = :seat_id
""")

# batching: ceny pre VŠETKY sedadlá naraz → volá sa 1×
SQL_PRICES_MANY_SEATS = text("""
    SELECT seat_id, amount_cents, currency, internal_cost_cents
    FROM prices
    WHERE event_id = :event_id AND seat_id IN :seat_ids
""").bindparams(bindparam("seat_ids", expanding=True))

SQL_EVENT = text("SELECT id, name, venue FROM events WHERE id = :event_id")


# ════════════════════════════════════════════════════════════════════════
# 2. Typy schémy a ich resolvery
#    Resolver = funkcia, ktorá naplní jedno pole. Klient vyberá polia, server rozhoduje, ako ich načíta.
# ════════════════════════════════════════════════════════════════════════

@strawberry.type(description="Cena sedadla")
class Price:
    amount: float = strawberry.field(description="Suma v EUR")
    currency: str
    internal_cost_cents: strawberry.Private[int]     # Private = nie je v schéme, klient to nevidí

    @strawberry.field(description="Interný náklad v EUR — iba pre rolu admin")
    def internal_cost(self, info: Info) -> float:
        # Autorizácia na úrovni POĽA, nie celého endpointu
        if info.context.role != "admin":
            raise PermissionError("Prístup zamietnutý: pole internalCost vyžaduje rolu admin.")
        return self.internal_cost_cents / 100


@strawberry.type(description="Sedadlo")
class Seat:
    id: strawberry.ID
    row: str
    number: int
    event_id: strawberry.Private[str]

    @strawberry.field(description="Cena — naivne 1 SQL na sedadlo, alebo cez DataLoader dávkovo")
    # ── ukážka C3 ──
    async def price(self, info: Info) -> Price | None:
        # Tento resolver sa zavolá PRE KAŽDÉ sedadlo (100×). Celý rozdiel dema je tu:
        if info.context.mode == "naive":
            return await price_naive(info.context, self.event_id, self.id)
        return await price_batched(info.context, self.event_id, self.id)
    # ── /ukážka C3 ──


@strawberry.type(description="Udalosť (koncert)")
class Event:
    id: strawberry.ID

    @strawberry.field(description=f"Sedadlá udalosti, limit 1–{GRAPHQL_MAX_LIMIT}")
    async def seats(self, info: Info, limit: int = 10) -> list[Seat]:
        # Ochrana: klient si nemôže vypýtať milión riadkov
        if not 1 <= limit <= GRAPHQL_MAX_LIMIT:
            raise ValueError(f"limit musí byť 1–{GRAPHQL_MAX_LIMIT} (dostal som {limit}). "
                             "Ochrana proti drahým query.")
        rows = await info.context.fetch(SQL_SEATS, {"event_id": self.id, "limit": limit})
        return [Seat(id=r.seat_id, row=r.row_label, number=r.seat_number, event_id=self.id) for r in rows]

    # name / venue sa načítajú z DB iba vtedy, ak ich query naozaj obsahuje
    @strawberry.field
    async def name(self, info: Info) -> str | None:
        row = await load_event(info.context, self.id)
        return row.name if row else None

    @strawberry.field
    async def venue(self, info: Info) -> str | None:
        row = await load_event(info.context, self.id)
        return row.venue if row else None


@strawberry.type
class Query:
    @strawberry.field(description="Referencia na udalosť; samotné volanie nerobí SQL dotaz")
    def event(self, id: strawberry.ID) -> Event:
        return Event(id=id)


# Ochrana: maximálna hĺbka vnorenia query
schema = strawberry.Schema(query=Query, extensions=[QueryDepthLimiter(max_depth=6)])


# ════════════════════════════════════════════════════════════════════════
# 3. Načítanie ceny: NAIVNE vs. BATCHING
# ════════════════════════════════════════════════════════════════════════

# ── ukážka C4 ──
async def price_naive(ctx: GQLContext, event_id: str, seat_id: str) -> Price | None:
    """N+1: každé sedadlo si urobí VLASTNÝ SQL dotaz → 100 sedadiel = 100 dotazov."""
    rows = await ctx.fetch(SQL_PRICE_ONE_SEAT, {"event_id": event_id, "seat_id": seat_id})
    return to_price(rows[0]) if rows else None


async def price_batched(ctx: GQLContext, event_id: str, seat_id: str) -> Price | None:
    """DataLoader: iba ZAPÍŠE kľúč. SQL sa spustí raz pre všetky zozbierané kľúče."""
    row = await ctx.price_loader.load((event_id, seat_id))
    return to_price(row) if row else None
# ── /ukážka C4 ──


# ── ukážka C5 ──
async def load_prices_in_one_query(ctx: GQLContext, keys: list[tuple[str, str]]) -> list:
    """Dávková funkcia DataLoadera.

    Dostane naraz všetky kľúče z jedného kola, napr. [('42','A1'), ('42','A2'), … 100×],
    urobí JEDEN SQL dotaz a vráti výsledky v ROVNAKOM poradí ako kľúče.
    """
    seats_by_event: dict[str, list[str]] = {}
    for event_id, seat_id in keys:
        seats_by_event.setdefault(event_id, []).append(seat_id)

    found = {}
    for event_id, seat_ids in seats_by_event.items():       # v deme je len event 42 → 1 dotaz
        rows = await ctx.fetch(SQL_PRICES_MANY_SEATS, {"event_id": event_id, "seat_ids": seat_ids})
        for row in rows:
            found[(event_id, row.seat_id)] = row

    return [found.get(key) for key in keys]
# ── /ukážka C5 ──


def to_price(row) -> Price:
    return Price(amount=row.amount_cents / 100, currency=row.currency.strip(),
                 internal_cost_cents=row.internal_cost_cents)


async def load_event(ctx: GQLContext, event_id: str):
    """Riadok udalosti — načíta sa najviac raz za request."""
    if event_id not in ctx.event_cache:
        rows = await ctx.fetch(SQL_EVENT, {"event_id": event_id})
        ctx.event_cache[event_id] = rows[0] if rows else None
    return ctx.event_cache[event_id]


# ════════════════════════════════════════════════════════════════════════
# 4. Kontext jedného requestu
#    Vzniká NOVÝ pre každý request → DataLoader cache sa nikdy nezdieľa medzi používateľmi.
# ════════════════════════════════════════════════════════════════════════

@dataclass
class GQLContext:
    conn: AsyncConnection          # jedno DB spojenie pre celý request (na ňom sa počíta SQL)
    mode: str                      # "naive" | "batch"
    role: str                      # "public" | "admin"
    price_loader: DataLoader | None = None
    event_cache: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def fetch(self, sql, params: dict) -> list:
        async with self.lock:      # príkazy na jednom spojení idú za sebou
            return (await self.conn.execute(sql, params)).all()


def build_context(conn: AsyncConnection, mode: str, role: str) -> GQLContext:
    ctx = GQLContext(conn=conn, mode=mode, role=role)
    ctx.price_loader = DataLoader(load_fn=lambda keys: load_prices_in_one_query(ctx, keys),
                                  max_batch_size=GRAPHQL_MAX_LIMIT)
    return ctx
