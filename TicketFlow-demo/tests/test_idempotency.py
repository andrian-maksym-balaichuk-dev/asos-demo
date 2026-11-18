"""Demo A — rovnaký retry ≠ nový nákup."""
from tests.conftest import create_pending

RESERVATION = {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"}


async def _active_count(client, seat):
    return (await client.get("/demo/state", params={"seat": seat})).json()["active_count"]


async def test_same_key_same_payload_returns_same_reservation(client):
    """Retry s rovnakým kľúčom vráti uloženú odpoveď (tie isté bajty) a nevytvorí druhú rezerváciu."""
    headers = {"Idempotency-Key": "retry-key-1"}

    first = await client.post("/reservations", json=RESERVATION, headers=headers)
    retry = await client.post("/reservations", json=RESERVATION, headers=headers)

    assert first.status_code == retry.status_code == 201
    assert first.headers["Idempotent-Replayed"] == "false"
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert first.json()["id"] == retry.json()["id"] == "r-001"
    assert first.content == retry.content  # presne tie isté bajty
    assert await _active_count(client, "A7") == 1


async def test_same_key_different_payload_is_rejected_without_side_effects(client):
    """Rovnaký kľúč s iným payloadom = chyba klienta (422) a v DB sa nič nevytvorí."""
    headers = {"Idempotency-Key": "retry-key-2"}
    await client.post("/reservations", json={"event_id": "42", "seat_id": "A7", "buyer_id": "anna"}, headers=headers)

    reused = await client.post("/reservations", json={"event_id": "42", "seat_id": "B2", "buyer_id": "anna"},
                               headers=headers)

    assert reused.status_code == 422
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await _active_count(client, "B2") == 0


async def test_concurrent_requests_with_same_key_create_one_reservation(client):
    """5 súbežných requestov s rovnakým kľúčom → všetky 201, ale jediná rezervácia."""
    import asyncio
    headers = {"Idempotency-Key": "parallel-key"}

    responses = await asyncio.gather(*[client.post("/reservations", json=RESERVATION, headers=headers)
                                       for _ in range(5)])

    assert {response.status_code for response in responses} == {201}
    assert len({response.json()["id"] for response in responses}) == 1


async def test_without_key_second_request_is_new_operation(client):
    """Bez kľúča server nevie, že ide o retry → druhý request je nový nákup → 409."""
    await create_pending(client)
    second = await client.post("/reservations", json=RESERVATION)
    assert second.status_code == 409  # bez kľúča je to nový nákup → sedadlo už je obsadené


async def test_validation_and_openapi(client):
    """Neplatný vstup → 422 VALIDATION_ERROR; OpenAPI dokumentuje 409; katalóg má 100 sedadiel."""
    invalid = await client.post("/reservations", json={"event_id": "42", "seat_id": "Z99", "buyer_id": "x"})
    assert invalid.status_code == 422 and invalid.json()["code"] == "VALIDATION_ERROR"

    spec = (await client.get("/openapi.json")).json()
    assert "/reservations" in spec["paths"]
    assert "409" in spec["paths"]["/reservations"]["post"]["responses"]
    assert (await client.get("/docs")).status_code == 200

    event = (await client.get("/events/42")).json()
    seats = (await client.get("/events/42/seats")).json()
    assert event["seats_total"] == len(seats) == 100
