"""Demo A — súbeh: rôzni kupujúci, rôzne kľúče, presne 1 víťaz. Garancia z PostgreSQL indexu."""
import asyncio

import httpx

from tests.conftest import BASE_URL


async def _attempt(i: int):
    # každý kupujúci má VLASTNÉHO klienta (vlastné TCP spojenie) → nezávislé požiadavky
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as buyer_client:
        return await buyer_client.post("/reservations",
                                       json={"event_id": "42", "seat_id": "A7", "buyer_id": f"buyer-{i}"},
                                       headers={"Idempotency-Key": f"race-{i}"})


async def _active_count(client):
    return (await client.get("/demo/state", params={"seat": "A7"})).json()["active_count"]


async def test_two_buyers_exactly_one_winner(client):
    """Dvaja naraz: jeden 201, druhý 409 SEAT_TAKEN; v DB jediná aktívna rezervácia."""
    first, second = await asyncio.gather(_attempt(1), _attempt(2))

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["code"] == "SEAT_TAKEN"
    assert await _active_count(client) == 1


async def test_twenty_buyers_exactly_one_winner(client):
    """20 naraz: presne 1× 201 a 19× 409 — žiadny „dvojitý predaj“."""
    responses = await asyncio.gather(*[_attempt(i) for i in range(20)])

    status_codes = [response.status_code for response in responses]
    assert status_codes.count(201) == 1 and status_codes.count(409) == 19
    assert await _active_count(client) == 1
