"""Integračné testy proti BEŽIACIM službám (docker compose).

Spúšťaj:  docker compose exec api pytest -q
Testy resetujú demo dáta (POST /demo/reset) — nespúšťaj ich počas prezentácie.
"""
import os

import httpx
import pytest

BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")
WS_URL = BASE_URL.replace("http", "ws", 1) + "/ws"


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as c:
        r = await c.post("/demo/reset")
        assert r.status_code == 200, r.text
        yield c


async def create_pending(client, buyer="buyer-anna", seat="A7", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    r = await client.post("/reservations", json={"event_id": "42", "seat_id": seat, "buyer_id": buyer},
                          headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(autouse=True)
async def _close_grpc_channels():
    yield
    from grpc_service.client import close_channels
    await close_channels()
