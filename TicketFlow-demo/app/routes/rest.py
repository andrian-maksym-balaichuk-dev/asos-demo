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


@router.get("/events/{event_id}", response_model=EventOut,
            responses={404: {"model": Problem, "description": "Udalosť neexistuje"}})
async def get_event(event_id: str = Path(pattern=EVENT_ID_PATTERN, examples=["42"])):
    async with engine.connect() as conn:
        row = (await conn.execute(text("""
            SELECT e.id, e.name, e.venue, e.starts_at,
                   count(s.seat_id) AS seats_total,
                   count(s.seat_id) FILTER (WHERE r.id IS NULL) AS seats_available
            FROM events e
            LEFT JOIN seats s ON s.event_id = e.id
            LEFT JOIN reservations r ON r.event_id = s.event_id AND r.seat_id = s.seat_id
                                    AND r.status IN ('PENDING', 'CONFIRMED')
            WHERE e.id = :id
            GROUP BY e.id"""), {"id": event_id})).first()
    if row is None:
        return problem(404, "EVENT_NOT_FOUND", "Udalosť neexistuje", f"Udalosť {event_id} sa nenašla.")
    m = dict(row._mapping)
    m["starts_at"] = m["starts_at"].isoformat()
    return m


@router.get("/events/{event_id}/seats", response_model=list[SeatOut],
            responses={404: {"model": Problem}})
async def get_seats(event_id: str = Path(pattern=EVENT_ID_PATTERN, examples=["42"])):
    async with engine.connect() as conn:
        rows = (await conn.execute(text("""
            SELECT s.seat_id, s.row_label, s.seat_number, p.amount_cents, p.currency,
                   COALESCE(r.status, 'FREE') AS status
            FROM seats s
            JOIN prices p ON p.event_id = s.event_id AND p.seat_id = s.seat_id
            LEFT JOIN reservations r ON r.event_id = s.event_id AND r.seat_id = s.seat_id
                                    AND r.status IN ('PENDING', 'CONFIRMED')
            WHERE s.event_id = :id
            ORDER BY s.row_label, s.seat_number"""), {"id": event_id})).all()
    if not rows:
        return problem(404, "EVENT_NOT_FOUND", "Udalosť neexistuje", f"Udalosť {event_id} nemá sedadlá.")
    return [{
        "seat_id": r.seat_id, "row": r.row_label, "number": r.seat_number,
        "price": {"amount_cents": r.amount_cents, "currency": r.currency.strip()},
        "status": r.status, "available": r.status == "FREE",
    } for r in rows]


def _request_hash(body: ReservationCreate) -> str:
    canonical = json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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
    req_hash = _request_hash(body)
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            if idempotency_key:
                claimed = (await conn.execute(text(
                    "INSERT INTO idempotency_keys (key, request_hash) VALUES (:k, :h) "
                    "ON CONFLICT (key) DO NOTHING RETURNING key"),
                    {"k": idempotency_key, "h": req_hash})).first()
                if claimed is None:
                    stored = (await conn.execute(text(
                        "SELECT request_hash, response_status, response_body FROM idempotency_keys WHERE key = :k"),
                        {"k": idempotency_key})).first()
                    await trans.rollback()
                    if stored.request_hash != req_hash:
                        return problem(422, "IDEMPOTENCY_KEY_REUSED", "Kľúč už bol použitý s iným payloadom",
                                       "Rovnaký Idempotency-Key s iným telom požiadavky je chyba klienta. "
                                       "Nič sa nezmenilo.")
                    log.info("idempotentný replay key=%s", idempotency_key)
                    # vrátime PRESNE tie isté bajty ako pri prvom volaní
                    return Response(stored.response_body, status_code=stored.response_status,
                                    media_type="application/json", headers={"Idempotent-Replayed": "true"})
            try:
                row = (await conn.execute(text(
                    "INSERT INTO reservations (event_id, seat_id, buyer_id, status) "
                    "VALUES (:e, :s, :b, 'PENDING') "
                    "RETURNING id, event_id, seat_id, buyer_id, status, created_at, updated_at"),
                    {"e": body.event_id, "s": body.seat_id, "b": body.buyer_id})).first()
            except IntegrityError as exc:
                await trans.rollback()
                diag = getattr(exc.orig, "diag", None)
                constraint = getattr(diag, "constraint_name", None)
                sqlstate = getattr(exc.orig, "sqlstate", None)
                if sqlstate == "23505" and constraint == "one_active_reservation_per_seat":
                    log.info("SEAT_TAKEN %s/%s buyer=%s", body.event_id, body.seat_id, body.buyer_id)
                    return problem(409, "SEAT_TAKEN", "Sedadlo je obsadené",
                                   f"Sedadlo {body.seat_id} už má aktívnu rezerváciu. Rozhodol PostgreSQL "
                                   "UNIQUE index one_active_reservation_per_seat.", constraint=constraint)
                if sqlstate == "23503":
                    return problem(404, "SEAT_NOT_FOUND", "Sedadlo neexistuje",
                                   f"Sedadlo {body.seat_id} pre udalosť {body.event_id} neexistuje.")
                raise
            reservation = serialize_reservation(dict(row._mapping))
            response_bytes = json.dumps(reservation, ensure_ascii=False, separators=(",", ":"))
            if idempotency_key:
                await conn.execute(text(
                    "UPDATE idempotency_keys SET reservation_id = :r, response_status = 201, "
                    "response_body = :b WHERE key = :k"),
                    {"r": reservation["id"], "b": response_bytes, "k": idempotency_key})
            await trans.commit()
        except BaseException:
            if trans.is_active:
                await trans.rollback()
            raise
    # notifikácia až PO commite
    await manager.broadcast({"type": "reservation.created", "reservation": reservation,
                             "correlation_id": correlation_id.get()})
    return Response(response_bytes, status_code=201, media_type="application/json",
                    headers={"Idempotent-Replayed": "false"})


@router.get("/reservations/{reservation_id}", response_model=ReservationOut,
            summary="Snapshot rezervácie (zdroj pravdy po reconnecte)",
            responses={404: {"model": Problem}})
async def read_reservation(reservation_id: str = Path(pattern=r"^r-[0-9]{3,9}$", examples=["r-001"])):
    async with engine.connect() as conn:
        r = await get_reservation(conn, reservation_id)
    if r is None:
        return problem(404, "RESERVATION_NOT_FOUND", "Rezervácia neexistuje", f"{reservation_id} sa nenašla.")
    return JSONResponse({**r, "snapshot_at": now_iso()})
