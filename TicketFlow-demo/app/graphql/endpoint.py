"""HTTP endpointy GraphQL. Každý request: nové DB spojenie + nový DataLoader + vlastný SQL log.

POST /graphql          → batch režim (DataLoader)
POST /graphql/naive    → naivné resolvery (N+1)
Odpoveď obsahuje `extensions.sql` = skutočne zaznamenané príkazy z event hooku.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.common import correlation_id
from app.data.db import recorded_connection
from app.graphql.schema import DEMO_QUERY, build_context, schema

router = APIRouter(tags=["Demo C — GraphQL"])


class GraphQLRequest(BaseModel):
    query: str = Field(max_length=4000, examples=[DEMO_QUERY])
    variables: dict | None = None
    operationName: str | None = None


async def _run(req: GraphQLRequest, mode: str, role: str) -> JSONResponse:
    role = "admin" if role == "admin" else "public"
    t0 = time.perf_counter()
    async with recorded_connection() as (conn, sql_log):
        ctx = build_context(conn, mode, role)
        result = await schema.execute(req.query, variable_values=req.variables,
                                      operation_name=req.operationName, context_value=ctx)
        statements = list(sql_log)
    duration_ms = round((time.perf_counter() - t0) * 1000, 1)
    body: dict = {"data": result.data}
    if result.errors:
        body["errors"] = [e.formatted for e in result.errors]
    body["extensions"] = {
        "resolverMode": mode,
        "role": role,
        "sql": {
            "count": len(statements),
            "source": "SQLAlchemy before_cursor_execute hook na DB spojení tohto requestu",
            "statements": statements,
        },
        "durationMs": duration_ms,
        "durationNote": "orientačné lokálne meranie, nie benchmark",
        "correlationId": correlation_id.get(),
    }
    return JSONResponse(body, status_code=200)


@router.post("/graphql", summary="GraphQL — batching (DataLoader)")
async def graphql_batch(req: GraphQLRequest, x_demo_role: str = Header(default="public")):
    return await _run(req, "batch", x_demo_role)


@router.post("/graphql/naive", summary="GraphQL — naivné resolvery (N+1)")
async def graphql_naive(req: GraphQLRequest, x_demo_role: str = Header(default="public")):
    return await _run(req, "naive", x_demo_role)


@router.get("/graphql/schema.graphql", summary="SDL schéma", response_class=JSONResponse)
async def graphql_sdl():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(schema.as_str())
