"""Demo D — duplicitná udalosť sa prijme bezpečne, stav sa zmení presne raz."""
import asyncio

from tests.conftest import create_pending


async def test_replay_is_idempotent(client):
    """Zopakovaná udalosť (rovnaké event id aj raw body) → 200 DUPLICATE_IGNORED, nie druhé spracovanie."""
    reservation_id = (await create_pending(client))["id"]

    first = (await client.post("/demo/provider/payment", json={"reservation_id": reservation_id})).json()
    replay = (await client.post("/demo/provider/replay", json={})).json()

    assert first["received"]["body"]["outcome"] == "CONFIRMED"
    assert replay["received"]["status"] == 200
    assert replay["received"]["body"]["result"] == "DUPLICATE_IGNORED"
    assert replay["received"]["body"]["event_id"] == first["received"]["body"]["event_id"]
    assert replay["sent"]["raw_body"] == first["sent"]["raw_body"]


async def test_concurrent_duplicates_processed_once(client):
    """5 súbežných duplikátov po spracovanej udalosti → všetky DUPLICATE_IGNORED."""
    reservation_id = (await create_pending(client))["id"]
    await client.post("/demo/provider/payment", json={"reservation_id": reservation_id})

    responses = await asyncio.gather(*[client.post("/demo/provider/replay", json={}) for _ in range(5)])

    outcomes = [response.json()["received"]["body"]["result"] for response in responses]
    assert outcomes == ["DUPLICATE_IGNORED"] * 5
