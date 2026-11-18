"""Demo C — rovnaký JSON, 101 vs 2 SKUTOČNÉ SQL dotazy (z SQLAlchemy event hooku)."""
from app.graphql.schema import DEMO_QUERY


async def _q(client, path, query=DEMO_QUERY, headers=None):
    r = await client.post(path, json={"query": query}, headers=headers or {})
    assert r.status_code == 200
    return r.json()


async def test_naive_101_batched_2_same_data(client):
    naive = await _q(client, "/graphql/naive")
    batch = await _q(client, "/graphql")
    assert "errors" not in naive and "errors" not in batch
    assert naive["data"] == batch["data"]
    assert len(batch["data"]["event"]["seats"]) == 100
    assert naive["extensions"]["sql"]["count"] == 101
    assert batch["extensions"]["sql"]["count"] == 2
    stmts = batch["extensions"]["sql"]["statements"]
    assert "FROM seats" in stmts[0]["sql"] and " IN (" in stmts[1]["sql"]
    naive_price = [s for s in naive["extensions"]["sql"]["statements"] if "FROM prices" in s["sql"]]
    assert len(naive_price) == 100


async def test_counts_scale_with_real_semantics(client):
    q = '{ event(id: "42") { seats(limit: 10) { id price { amount } } } }'
    assert (await _q(client, "/graphql/naive", q))["extensions"]["sql"]["count"] == 11
    assert (await _q(client, "/graphql", q))["extensions"]["sql"]["count"] == 2
    q2 = '{ event(id: "42") { name seats(limit: 10) { id } } }'  # name pridá 1 skutočný dotaz
    assert (await _q(client, "/graphql", q2))["extensions"]["sql"]["count"] == 2


async def test_limit_over_100_rejected(client):
    r = await _q(client, "/graphql", '{ event(id: "42") { seats(limit: 500) { id } } }')
    assert r["errors"] and "limit" in r["errors"][0]["message"]
    assert r["extensions"]["sql"]["count"] == 0


async def test_privileged_field_requires_role(client):
    q = '{ event(id: "42") { seats(limit: 1) { id price { internalCost } } } }'
    public = await _q(client, "/graphql", q)
    assert public["errors"] and "admin" in public["errors"][0]["message"]
    admin = await _q(client, "/graphql", q, {"X-Demo-Role": "admin"})
    assert "errors" not in admin and admin["data"]["event"]["seats"][0]["price"]["internalCost"] == 31.0


async def test_depth_limit(client):
    deep = "{ " + "event(id: \"42\") { seats(limit: 1) { price { amount } } }" + " }"
    assert "errors" not in await _q(client, "/graphql", deep)


async def test_loader_is_request_scoped(client):
    from app.graphql.schema import build_context
    a, b = build_context(None, "batch", "public"), build_context(None, "batch", "admin")
    assert a.price_loader is not b.price_loader
