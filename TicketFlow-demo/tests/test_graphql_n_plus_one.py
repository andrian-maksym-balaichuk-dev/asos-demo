"""Demo C — rovnaký JSON, 101 vs 2 SKUTOČNÉ SQL dotazy (z SQLAlchemy event hooku)."""
from app.graphql.schema import DEMO_QUERY


async def _q(client, path, query=DEMO_QUERY, headers=None):
    """Pošle GraphQL query; GraphQL vracia 200 aj pri chybách (sú v poli "errors")."""
    response = await client.post(path, json={"query": query}, headers=headers or {})
    assert response.status_code == 200
    return response.json()


def _sql_count(result):
    return result["extensions"]["sql"]["count"]


async def test_naive_101_batched_2_same_data(client):
    """Rovnaké dáta, ale naivne 1 + 100 SQL a s DataLoaderom 1 + 1 SQL."""
    naive = await _q(client, "/graphql/naive")
    batched = await _q(client, "/graphql")

    assert "errors" not in naive and "errors" not in batched
    assert naive["data"] == batched["data"]
    assert len(batched["data"]["event"]["seats"]) == 100
    assert _sql_count(naive) == 101
    assert _sql_count(batched) == 2

    # batching: 1. dotaz sedadlá, 2. dotaz všetky ceny cez IN (...)
    batched_statements = batched["extensions"]["sql"]["statements"]
    assert "FROM seats" in batched_statements[0]["sql"] and " IN (" in batched_statements[1]["sql"]
    # naivne: pre každé sedadlo vlastný dotaz na cenu
    naive_price_statements = [s for s in naive["extensions"]["sql"]["statements"] if "FROM prices" in s["sql"]]
    assert len(naive_price_statements) == 100


async def test_counts_scale_with_real_semantics(client):
    """Počty nie sú natvrdo: 10 sedadiel → naivne 11; batching vždy 2; pole name pridá 1 skutočný dotaz."""
    ten_seats_with_price = '{ event(id: "42") { seats(limit: 10) { id price { amount } } } }'
    assert _sql_count(await _q(client, "/graphql/naive", ten_seats_with_price)) == 11
    assert _sql_count(await _q(client, "/graphql", ten_seats_with_price)) == 2

    name_and_seats = '{ event(id: "42") { name seats(limit: 10) { id } } }'  # name pridá 1 skutočný dotaz
    assert _sql_count(await _q(client, "/graphql", name_and_seats)) == 2


async def test_limit_over_100_rejected(client):
    """Príliš veľký limit sa odmietne skôr, než sa spustí akýkoľvek SQL dotaz."""
    result = await _q(client, "/graphql", '{ event(id: "42") { seats(limit: 500) { id } } }')
    assert result["errors"] and "limit" in result["errors"][0]["message"]
    assert _sql_count(result) == 0


async def test_privileged_field_requires_role(client):
    """Autorizácia na úrovni poľa: internalCost vidí iba rola admin."""
    query = '{ event(id: "42") { seats(limit: 1) { id price { internalCost } } } }'

    public = await _q(client, "/graphql", query)
    assert public["errors"] and "admin" in public["errors"][0]["message"]

    admin = await _q(client, "/graphql", query, {"X-Demo-Role": "admin"})
    assert "errors" not in admin and admin["data"]["event"]["seats"][0]["price"]["internalCost"] == 31.0


async def test_depth_limit(client):
    """Bežná vnorená query je v rámci limitu hĺbky a prejde bez chýb."""
    query_within_depth = "{ " + "event(id: \"42\") { seats(limit: 1) { price { amount } } }" + " }"
    assert "errors" not in await _q(client, "/graphql", query_within_depth)


async def test_loader_is_request_scoped(client):
    """Každý request má vlastný DataLoader → cache sa nezdieľa medzi používateľmi/rolami."""
    from app.graphql.schema import build_context
    public_context = build_context(None, "batch", "public")
    admin_context = build_context(None, "batch", "admin")
    assert public_context.price_loader is not admin_context.price_loader
