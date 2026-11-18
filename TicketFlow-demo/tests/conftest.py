"""Integračné testy proti BEŽIACIM službám (docker compose).

Spustenie:  docker compose exec api pytest -q
Testy resetujú demo dáta (POST /demo/reset) — nespúšťaj ich počas prezentácie.
"""
import os

import httpx
import pytest

BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")
WS_URL = BASE_URL.replace("http", "ws", 1) + "/ws"


@pytest.fixture
async def client():
    """HTTP klient na API; každý test začína z čistých demo dát."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as http:
        reset = await http.post("/demo/reset")
        assert reset.status_code == 200, reset.text
        yield http


async def create_pending(client, buyer="buyer-anna", seat="A7", key=None):
    """Vytvorí rezerváciu v stave PENDING a vráti jej JSON."""
    headers = {"Idempotency-Key": key} if key else {}
    response = await client.post("/reservations", json={"event_id": "42", "seat_id": seat, "buyer_id": buyer},
                                 headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(autouse=True)
async def _close_grpc_channels():
    # gRPC kanál je viazaný na event loop a pytest má loop na test → po teste ho zatvor
    yield
    from grpc_service.client import close_channels
    await close_channels()
