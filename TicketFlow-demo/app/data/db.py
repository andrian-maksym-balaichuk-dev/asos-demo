"""Async SQLAlchemy engine + skutočné počítanie SQL dotazov cez event hook.

`recorded_connection()` pripojí na konkrétne DB spojenie zoznam `query_log`.
Hook `before_cursor_execute` zapíše KAŽDÝ príkaz, ktorý SQLAlchemy pošle
cez DBAPI kurzor na tomto spojení. Číslo 101 / 2 v Deme C pochádza odtiaľto,
nie je nikde nastavené ručne.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app import config


# ════════════════════════════════════════════════════════════════════════
# 1. Engine — jeden pool spojení pre celý proces
# ════════════════════════════════════════════════════════════════════════

engine: AsyncEngine = create_async_engine(
    config.DATABASE_URL, pool_size=10, max_overflow=20, pool_recycle=1800
)


# ════════════════════════════════════════════════════════════════════════
# 2. Počítanie SQL dotazov (Demo C — GraphQL N+1)
# ════════════════════════════════════════════════════════════════════════

# Kľúč v conn.info: log existuje len na spojeniach z recorded_connection()
QUERY_LOG_KEY = "ticketflow_query_log"
MAX_LOGGED_PARAMS = 12


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _record_statement(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
    query_log = conn.info.get(QUERY_LOG_KEY)
    if query_log is not None:
        query_log.append({"sql": " ".join(statement.split()), "params": _safe_params(parameters)})


def _safe_params(parameters: Any) -> Any:
    """Parametre skrátené a prevedené na JSON-kompatibilné typy (idú do odpovede)."""
    if isinstance(parameters, dict):
        return {name: (value if isinstance(value, (int, float, str, bool)) or value is None else str(value))
                for name, value in list(parameters.items())[:MAX_LOGGED_PARAMS]}
    if isinstance(parameters, (list, tuple)):
        return [str(value) for value in parameters[:MAX_LOGGED_PARAMS]]
    return str(parameters)


@asynccontextmanager
async def recorded_connection():
    """Spojenie v AUTOCOMMIT režime (žiadny implicitný BEGIN) s vlastným SQL logom."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        query_log: list[dict] = []
        conn.sync_connection.info[QUERY_LOG_KEY] = query_log
        try:
            yield conn, query_log
        finally:
            # spojenie sa vracia do poolu → log musí zmiznúť, inak by počítal cudzie dotazy
            conn.sync_connection.info.pop(QUERY_LOG_KEY, None)


# ════════════════════════════════════════════════════════════════════════
# 3. Drobné pomôcky
# ════════════════════════════════════════════════════════════════════════

async def ping() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def fetch_all(conn: AsyncConnection, sql: str, **params) -> list[dict]:
    result = await conn.execute(text(sql), params)
    return [dict(row._mapping) for row in result]
