"""Demo A — REST: zdroje /events a /reservations, Idempotency-Key a súbeh.

Kontrakt Idempotency-Key (zdokumentovaný aj v OpenAPI):
* Hlavička je voliteľná. Bez nej je každý POST nová logická operácia.
* Rovnaký kľúč + rovnaký payload → server NEVYTVORÍ novú rezerváciu, vráti
  uloženú pôvodnú odpoveď (rovnaký status, rovnaké reservation_id)
  a hlavičku `Idempotent-Replayed: true`.
* Rovnaký kľúč + iný payload → 422 IDEMPOTENCY_KEY_REUSED, nič sa nezmení
  (podľa draft-ietf-httpapi-idempotency-key-header).
* Ukladajú sa len úspešné výsledky. Ak sa pôvodný pokus skončil chybou
  (napr. 409), transakcia sa vráti a kľúč ostane nepoužitý.
* Súbežné requesty s tým istým kľúčom: druhý počká na zámok riadku
  idempotency_keys v PostgreSQL a potom vráti uložený výsledok.

Súbeh dvoch RÔZNYCH kupujúcich rieši iba databáza: čiastočný UNIQUE index
`one_active_reservation_per_seat`. Nikde nie je Python lock.
"""
from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Header, Path
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.common import correlation_id, now_iso, problem
from app.data.db import engine
from app.data.queries import get_reservation, serialize_reservation
from app.websocket.manager import manager

log = logging.getLogger("ticketflow.rest")
router = APIRouter(tags=["Demo A — REST"])

EVENT_ID_PATTERN = r"^[0-9]{1,6}$"
SEAT_ID_PATTERN = r"^[A-J](10|[1-9])$"

# PostgreSQL SQLSTATE kódy, na ktoré reagujeme
UNIQUE_VIOLATION = "23505"        # → 409 SEAT_TAKEN
FOREIGN_KEY_VIOLATION = "23503"   # → 404 SEAT_NOT_FOUND
SEAT_UNIQUE_INDEX = "one_active_reservation_per_seat"


# ════════════════════════════════════════════════════════════════════════
# 1. SQL dotazy (parametrizované — hodnoty od klienta nikdy nie sú v texte SQL)
# ════════════════════════════════════════════════════════════════════════

# Aktívna rezervácia = PENDING alebo CONFIRMED; voľné sedadlo nemá žiadnu
SQL_EVENT_WITH_COUNTS = text("""
    SELECT e.id, e.name, e.venue, e.starts_at,
           count(s.seat_id) AS seats_total,
           count(s.seat_id) FILTER (WHERE r.id IS NULL) AS seats_available
    FROM events e
    LEFT JOIN seats s ON s.event_id = e.id
    LEFT JOIN reservations r ON r.event_id = s.event_id AND r.seat_id = s.seat_id
                            AND r.status IN ('PENDING', 'CONFIRMED')
    WHERE e.id = :event_id
    GROUP BY e.id
""")

SQL_SEATS_WITH_STATUS = text("""
    SELECT s.seat_id, s.row_label, s.seat_number, p.amount_cents, p.currency,
           COALESCE(r.status, 'FREE') AS status
    FROM seats s
    JOIN prices p ON p.event_id = s.event_id AND p.seat_id = s.seat_id
    LEFT JOIN reservations r ON r.event_id = s.event_id AND r.seat_id = s.seat_id
                            AND r.status IN ('PENDING', 'CONFIRMED')
    WHERE s.event_id = :event_id
    ORDER BY s.row_label, s.seat_number
""")

# ON CONFLICT DO NOTHING: ak kľúč už existuje, RETURNING nevráti nič.
# Súbežný request s rovnakým kľúčom tu počká na zámok riadku.
SQL_CLAIM_IDEMPOTENCY_KEY = text("""
    INSERT INTO idempotency_keys (key, request_hash)
    VALUES (:key, :request_hash)
    ON CONFLICT (key) DO NOTHING
    RETURNING key
""")

SQL_STORED_IDEMPOTENT_RESPONSE = text("""
    SELECT request_hash, response_status, response_body
    FROM idempotency_keys
    WHERE key = :key
""")

# Súbeh rieši UNIQUE index one_active_reservation_per_seat, nie tento kód
SQL_INSERT_PENDING_RESERVATION = text("""
    INSERT INTO reservations (event_id, seat_id, buyer_id, status)
    VALUES (:event_id, :seat_id, :buyer_id, 'PENDING')
    RETURNING id, event_id, seat_id, buyer_id, status, created_at, updated_at
""")

SQL_STORE_IDEMPOTENT_RESPONSE = text("""
    UPDATE idempotency_keys
    SET reservation_id = :reservation_id, response_status = 201, response_body = :response_body
    WHERE key = :key
""")


# ════════════════════════════════════════════════════════════════════════
# 2. Modely — z nich FastAPI generuje OpenAPI kontrakt (/docs)
# ════════════════════════════════════════════════════════════════════════

# Chybová odpoveď podľa RFC 9457 (application/problem+json) — vyrába ju app.common.problem()
class Problem(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str
    correlation_id: str
    timestamp: str


class PriceOut(BaseModel):
    amount_cents: int
    currency: str


class EventOut(BaseModel):
    id: str
    name: str
    venue: str
    starts_at: str
    seats_total: int
    seats_available: int


class SeatOut(BaseModel):
    seat_id: str
    row: str
    number: int
    price: PriceOut
    status: str = Field(description="FREE | PENDING | CONFIRMED")
    available: bool


class ReservationCreate(BaseModel):
    # extra="forbid": neznáme polia sú chyba klienta, nie ticho ignorované
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"}]})
    event_id: str = Field(pattern=EVENT_ID_PATTERN)
    seat_id: str = Field(pattern=SEAT_ID_PATTERN)
    buyer_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


class ReservationOut(BaseModel):
    id: str
    event_id: str
    seat_id: str
    buyer_id: str
    status: str = Field(description="PENDING | CONFIRMED | CANCELLED")
    created_at: str
    updated_at: str


# ════════════════════════════════════════════════════════════════════════
# 3. GET /events — čítanie zdrojov
# ════════════════════════════════════════════════════════════════════════

@router.get("/events/{event_id}", response_model=EventOut,
            responses={404: {"model": Problem, "description": "Udalosť neexistuje"}})
async def get_event(event_id: str = Path(pattern=EVENT_ID_PATTERN, examples=["42"])):
    async with engine.connect() as conn:
        row = (await conn.execute(SQL_EVENT_WITH_COUNTS, {"event_id": event_id})).first()
    if row is None:
        return problem(404, "EVENT_NOT_FOUND", "Udalosť neexistuje", f"Udalosť {event_id} sa nenašla.")
    event = dict(row._mapping)
    event["starts_at"] = event["starts_at"].isoformat()
    return event


@router.get("/events/{event_id}/seats", response_model=list[SeatOut],
            responses={404: {"model": Problem}})
async def get_seats(event_id: str = Path(pattern=EVENT_ID_PATTERN, examples=["42"])):
    async with engine.connect() as conn:
        rows = (await conn.execute(SQL_SEATS_WITH_STATUS, {"event_id": event_id})).all()
    if not rows:
        return problem(404, "EVENT_NOT_FOUND", "Udalosť neexistuje", f"Udalosť {event_id} nemá sedadlá.")
    return [_seat_to_json(seat) for seat in rows]


def _seat_to_json(seat) -> dict:
    return {
        "seat_id": seat.seat_id,
        "row": seat.row_label,
        "number": seat.seat_number,
        "price": {"amount_cents": seat.amount_cents, "currency": seat.currency.strip()},  # CHAR(3) → bez medzier
        "status": seat.status,
        "available": seat.status == "FREE",
    }


# ════════════════════════════════════════════════════════════════════════
# 4. POST /reservations — idempotencia + súbeh
# ════════════════════════════════════════════════════════════════════════

@router.post(
    "/reservations", status_code=201, response_model=ReservationOut,
    summary="Vytvor rezerváciu (PENDING)",
    description=__doc__,
    responses={
        201: {"description": "Rezervácia vytvorená alebo idempotentne zopakovaná (hlavička Idempotent-Replayed)"},
        404: {"model": Problem, "description": "Sedadlo alebo udalosť neexistuje"},
        409: {"model": Problem, "description": "SEAT_TAKEN — sedadlo už má aktívnu rezerváciu"},
        422: {"model": Problem, "description": "IDEMPOTENCY_KEY_REUSED alebo neplatný payload"},
    },
)
async def create_reservation(
    body: ReservationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=255,
                                         description="Voliteľný kľúč logickej operácie (napr. UUID)."),
):
    request_hash = _request_hash(body)

    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            # 1. Zaber Idempotency-Key. Ak už existuje → replay uloženej odpovede alebo 422.
            if idempotency_key:
                stored = await _claim_idempotency_key(conn, idempotency_key, request_hash)
                if stored is not None:
                    await transaction.rollback()
                    return _replay_or_reject(stored, request_hash, idempotency_key)

            # 2. Vlož PENDING rezerváciu. O súbehu rozhodne UNIQUE index v PostgreSQL.
            try:
                row = await _insert_pending_reservation(conn, body)
            except IntegrityError as exc:
                await transaction.rollback()
                error_response = _integrity_error_to_problem(exc, body)
                if error_response is None:
                    raise
                return error_response

            reservation = serialize_reservation(dict(row._mapping))
            response_json = json.dumps(reservation, ensure_ascii=False, separators=(",", ":"))

            # 3. Ulož odpoveď ku kľúču — v tej istej transakcii ako rezerváciu
            if idempotency_key:
                await _store_idempotent_response(conn, idempotency_key, reservation["id"], response_json)

            # 4. Commit: rezervácia aj kľúč vzniknú naraz, alebo vôbec
            await transaction.commit()
        except BaseException:
            if transaction.is_active:
                await transaction.rollback()
            raise

    # 5. WebSocket notifikácia až PO commite — klienti nevidia nič, čo by sa mohlo vrátiť
    await manager.broadcast({"type": "reservation.created", "reservation": reservation,
                             "correlation_id": correlation_id.get()})
    return Response(response_json, status_code=201, media_type="application/json",
                    headers={"Idempotent-Replayed": "false"})


# ── Pomocné kroky pre POST /reservations ─────────────────────────────────

def _request_hash(body: ReservationCreate) -> str:
    """Odtlačok payloadu — kanonický JSON, aby poradie kľúčov nehralo rolu."""
    canonical = json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _claim_idempotency_key(conn, key: str, request_hash: str):
    """None = kľúč je nový a patrí nám. Inak vráti uložený riadok z idempotency_keys."""
    claimed = (await conn.execute(SQL_CLAIM_IDEMPOTENCY_KEY,
                                  {"key": key, "request_hash": request_hash})).first()
    if claimed is not None:
        return None
    return (await conn.execute(SQL_STORED_IDEMPOTENT_RESPONSE, {"key": key})).first()


def _replay_or_reject(stored, request_hash: str, key: str) -> Response:
    if stored.request_hash != request_hash:
        return problem(422, "IDEMPOTENCY_KEY_REUSED", "Kľúč už bol použitý s iným payloadom",
                       "Rovnaký Idempotency-Key s iným telom požiadavky je chyba klienta. "
                       "Nič sa nezmenilo.")
    log.info("idempotentný replay key=%s", key)
    # vrátime PRESNE tie isté bajty ako pri prvom volaní (stĺpec response_body)
    return Response(stored.response_body, status_code=stored.response_status,
                    media_type="application/json", headers={"Idempotent-Replayed": "true"})


async def _insert_pending_reservation(conn, body: ReservationCreate):
    params = {"event_id": body.event_id, "seat_id": body.seat_id, "buyer_id": body.buyer_id}
    return (await conn.execute(SQL_INSERT_PENDING_RESERVATION, params)).first()


def _integrity_error_to_problem(exc: IntegrityError, body: ReservationCreate) -> JSONResponse | None:
    """Preloží chybu z PostgreSQL na HTTP odpoveď. None = neočakávaná chyba (propaguje sa ďalej)."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)

    if sqlstate == UNIQUE_VIOLATION and constraint == SEAT_UNIQUE_INDEX:
        log.info("SEAT_TAKEN %s/%s buyer=%s", body.event_id, body.seat_id, body.buyer_id)
        return problem(409, "SEAT_TAKEN", "Sedadlo je obsadené",
                       f"Sedadlo {body.seat_id} už má aktívnu rezerváciu. Rozhodol PostgreSQL "
                       "UNIQUE index one_active_reservation_per_seat.", constraint=constraint)
    if sqlstate == FOREIGN_KEY_VIOLATION:
        return problem(404, "SEAT_NOT_FOUND", "Sedadlo neexistuje",
                       f"Sedadlo {body.seat_id} pre udalosť {body.event_id} neexistuje.")
    return None


async def _store_idempotent_response(conn, key: str, reservation_id: str, response_json: str) -> None:
    await conn.execute(SQL_STORE_IDEMPOTENT_RESPONSE,
                       {"reservation_id": reservation_id, "response_body": response_json, "key": key})


# ════════════════════════════════════════════════════════════════════════
# 5. GET /reservations/{id} — snapshot (zdroj pravdy po WebSocket reconnecte)
# ════════════════════════════════════════════════════════════════════════

@router.get("/reservations/{reservation_id}", response_model=ReservationOut,
            summary="Snapshot rezervácie (zdroj pravdy po reconnecte)",
            responses={404: {"model": Problem}})
async def read_reservation(reservation_id: str = Path(pattern=r"^r-[0-9]{3,9}$", examples=["r-001"])):
    async with engine.connect() as conn:
        reservation = await get_reservation(conn, reservation_id)
    if reservation is None:
        return problem(404, "RESERVATION_NOT_FOUND", "Rezervácia neexistuje", f"{reservation_id} sa nenašla.")
    return JSONResponse({**reservation, "snapshot_at": now_iso()})
