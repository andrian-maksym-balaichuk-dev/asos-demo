"""Schéma PostgreSQL. Invarianty sú vynútené DATABÁZOU, nie Python kódom.

Kľúčové garancie:
* one_active_reservation_per_seat — čiastočný UNIQUE index: pre (event_id, seat_id)
  môže existovať najviac jedna rezervácia v stave PENDING alebo CONFIRMED.
  Toto rieši súbeh dvoch rôznych kupujúcich (Demo A).
* idempotency_keys.key PRIMARY KEY — jeden logický request = jeden záznam (Demo A).
* processed_webhook_events.event_id PRIMARY KEY — deduplikácia webhookov (Demo D).
* prices je samostatná tabuľka — umožňuje ukázať N+1 v GraphQL (Demo C).
"""

SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS events (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        venue      TEXT NOT NULL,
        starts_at  TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seats (
        event_id    TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        seat_id     TEXT NOT NULL CHECK (seat_id ~ '^[A-J](10|[1-9])$'),
        row_label   TEXT NOT NULL,
        seat_number INT  NOT NULL CHECK (seat_number BETWEEN 1 AND 10),
        PRIMARY KEY (event_id, seat_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prices (
        event_id            TEXT NOT NULL,
        seat_id             TEXT NOT NULL,
        amount_cents        INT  NOT NULL CHECK (amount_cents > 0),
        currency            CHAR(3) NOT NULL DEFAULT 'EUR',
        internal_cost_cents INT  NOT NULL CHECK (internal_cost_cents >= 0),
        PRIMARY KEY (event_id, seat_id),
        FOREIGN KEY (event_id, seat_id) REFERENCES seats(event_id, seat_id) ON DELETE CASCADE
    )
    """,
    "CREATE SEQUENCE IF NOT EXISTS reservation_seq",
    """
    CREATE TABLE IF NOT EXISTS reservations (
        id         TEXT PRIMARY KEY DEFAULT ('r-' || lpad(nextval('reservation_seq')::text, 3, '0')),
        event_id   TEXT NOT NULL,
        seat_id    TEXT NOT NULL,
        buyer_id   TEXT NOT NULL CHECK (length(buyer_id) BETWEEN 1 AND 64),
        status     TEXT NOT NULL CHECK (status IN ('PENDING', 'CONFIRMED', 'CANCELLED')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        FOREIGN KEY (event_id, seat_id) REFERENCES seats(event_id, seat_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS one_active_reservation_per_seat
        ON reservations (event_id, seat_id)
        WHERE status IN ('PENDING', 'CONFIRMED')
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        key             TEXT PRIMARY KEY CHECK (length(key) BETWEEN 1 AND 255),
        request_hash    TEXT NOT NULL,
        reservation_id  TEXT REFERENCES reservations(id) ON DELETE CASCADE,
        response_status INT,
        response_body   TEXT,           -- presné bajty pôvodnej odpovede
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processed_webhook_events (
        event_id       TEXT PRIMARY KEY,
        event_type     TEXT NOT NULL,
        reservation_id TEXT,
        outcome        TEXT NOT NULL,
        received_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]

ACTIVE_STATUSES = ("PENDING", "CONFIRMED")
