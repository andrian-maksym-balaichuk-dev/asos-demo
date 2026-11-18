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

engine: AsyncEngine = create_async_engine(
    config.DATABASE_URL, pool_size=10, max_overflow=20, pool_recycle=1800
)

QUERY_LOG_KEY = "ticketflow_query_log"


def _safe_params(parameters: Any) -> Any:
    if isinstance(parameters, dict):
        return {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
                for k, v in list(parameters.items())[:12]}
    if isinstance(parameters, (list, tuple)):
        return [str(p) for p in parameters[:12]]
    return str(parameters)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _record_statement(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
    log = conn.info.get(QUERY_LOG_KEY)
    if log is not None:
        log.append({"sql": " ".join(statement.split()), "params": _safe_params(parameters)})


@asynccontextmanager
async def recorded_connection():
    """Spojenie v AUTOCOMMIT režime (žiadny implicitný BEGIN) s vlastným SQL logom."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        log: list[dict] = []
        conn.sync_connection.info[QUERY_LOG_KEY] = log
        try:
            yield conn, log
        finally:
            conn.sync_connection.info.pop(QUERY_LOG_KEY, None)


async def ping() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def fetch_all(conn: AsyncConnection, sql: str, **params) -> list[dict]:
    result = await conn.execute(text(sql), params)
    return [dict(r._mapping) for r in result]
