"""Demo A — súbeh: rôzni kupujúci, rôzne kľúče, presne 1 víťaz. Garancia z PostgreSQL indexu."""
import asyncio

import httpx

from tests.conftest import BASE_URL


async def _attempt(i: int):
    # každý kupujúci má VLASTNÉHO klienta (vlastné TCP spojenie) → nezávislé požiadavky
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as c:
        return await c.post("/reservations", json={"event_id": "42", "seat_id": "A7", "buyer_id": f"buyer-{i}"},
                            headers={"Idempotency-Key": f"race-{i}"})


async def test_two_buyers_exactly_one_winner(client):
    r1, r2 = await asyncio.gather(_attempt(1), _attempt(2))
    assert sorted([r1.status_code, r2.status_code]) == [201, 409]
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["code"] == "SEAT_TAKEN"
    state = (await client.get("/demo/state", params={"seat": "A7"})).json()
    assert state["active_count"] == 1


async def test_twenty_buyers_exactly_one_winner(client):
    rs = await asyncio.gather(*[_attempt(i) for i in range(20)])
    codes = [r.status_code for r in rs]
    assert codes.count(201) == 1 and codes.count(409) == 19
    assert (await client.get("/demo/state", params={"seat": "A7"})).json()["active_count"] == 1
