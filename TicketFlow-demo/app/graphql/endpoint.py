"""HTTP endpointy GraphQL.

    POST /graphql         → batching (DataLoader)
    POST /graphql/naive   → naivné resolvery (N+1)

Klient pošle iba TEXT query. Do databázy pristupuje výhradne server.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.common import correlation_id
from app.data.db import recorded_connection
from app.graphql.schema import DEMO_QUERY, build_context, schema

router = APIRouter(tags=["Demo C — GraphQL"])


class GraphQLRequest(BaseModel):
    """Telo requestu od klienta: {"query": "...", "variables": {...}}"""
    query: str = Field(max_length=4000, examples=[DEMO_QUERY])     # ochrana: max. 4000 znakov
    variables: dict | None = None
    operationName: str | None = None


@router.post("/graphql", summary="GraphQL — batching (DataLoader)")
async def graphql_batch(req: GraphQLRequest, x_demo_role: str = Header(default="public")):
    return await run_query(req, mode="batch", role=x_demo_role)


@router.post("/graphql/naive", summary="GraphQL — naivné resolvery (N+1)")
async def graphql_naive(req: GraphQLRequest, x_demo_role: str = Header(default="public")):
    return await run_query(req, mode="naive", role=x_demo_role)


async def run_query(req: GraphQLRequest, mode: str, role: str) -> JSONResponse:
    role = "admin" if role == "admin" else "public"     # demo rola; v produkcii z overeného tokenu
    started = time.perf_counter()

    # 1. nové DB spojenie so záznamom SQL + nový DataLoader iba pre tento request
    async with recorded_connection() as (conn, sql_log):
        ctx = build_context(conn, mode, role)

        # 2. Strawberry: parse → validácia voči schéme → limity → resolvery
        result = await schema.execute(req.query, variable_values=req.variables,
                                      operation_name=req.operationName, context_value=ctx)

    # 3. odpoveď: data v tvare query + chyby + (len pre demo) skutočné SQL príkazy
    body: dict = {"data": result.data}
    if result.errors:
        body["errors"] = [error.formatted for error in result.errors]
    body["extensions"] = {
        "resolverMode": mode,
        "role": role,
        "sql": {
            "count": len(sql_log),
            "source": "SQLAlchemy before_cursor_execute hook na DB spojení tohto requestu",
            "statements": sql_log,
        },
        "durationMs": round((time.perf_counter() - started) * 1000, 1),
        "durationNote": "orientačné lokálne meranie, nie benchmark",
        "correlationId": correlation_id.get(),
    }
    # GraphQL vracia 200 aj pri chybách v poliach — chyby sú v "errors"
    return JSONResponse(body, status_code=200)


@router.get("/graphql/schema.graphql", summary="Schéma (SDL)", response_class=PlainTextResponse)
async def graphql_sdl():
    return schema.as_str()
