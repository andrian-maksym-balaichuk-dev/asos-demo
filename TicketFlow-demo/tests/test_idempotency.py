"""Demo A — rovnaký retry ≠ nový nákup."""
from tests.conftest import create_pending


async def test_same_key_same_payload_returns_same_reservation(client):
    body = {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"}
    h = {"Idempotency-Key": "retry-key-1"}
    r1 = await client.post("/reservations", json=body, headers=h)
    r2 = await client.post("/reservations", json=body, headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r1.headers["Idempotent-Replayed"] == "false"
    assert r2.headers["Idempotent-Replayed"] == "true"
    assert r1.json()["id"] == r2.json()["id"] == "r-001"
    assert r1.content == r2.content  # presne tie isté bajty
    state = (await client.get("/demo/state", params={"seat": "A7"})).json()
    assert state["active_count"] == 1


async def test_same_key_different_payload_is_rejected_without_side_effects(client):
    h = {"Idempotency-Key": "retry-key-2"}
    await client.post("/reservations", json={"event_id": "42", "seat_id": "A7", "buyer_id": "anna"}, headers=h)
    r = await client.post("/reservations", json={"event_id": "42", "seat_id": "B2", "buyer_id": "anna"}, headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert (await client.get("/demo/state", params={"seat": "B2"})).json()["active_count"] == 0


async def test_concurrent_requests_with_same_key_create_one_reservation(client):
    import asyncio
    body = {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"}
    h = {"Idempotency-Key": "parallel-key"}
    rs = await asyncio.gather(*[client.post("/reservations", json=body, headers=h) for _ in range(5)])
    assert {r.status_code for r in rs} == {201}
    assert len({r.json()["id"] for r in rs}) == 1


async def test_without_key_second_request_is_new_operation(client):
    await create_pending(client)
    r = await client.post("/reservations", json={"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"})
    assert r.status_code == 409  # bez kľúča je to nový nákup → sedadlo už je obsadené


async def test_validation_and_openapi(client):
    r = await client.post("/reservations", json={"event_id": "42", "seat_id": "Z99", "buyer_id": "x"})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    spec = (await client.get("/openapi.json")).json()
    assert "/reservations" in spec["paths"]
    assert "409" in spec["paths"]["/reservations"]["post"]["responses"]
    assert (await client.get("/docs")).status_code == 200
    ev = (await client.get("/events/42")).json()
    seats = (await client.get("/events/42/seats")).json()
    assert ev["seats_total"] == len(seats) == 100
