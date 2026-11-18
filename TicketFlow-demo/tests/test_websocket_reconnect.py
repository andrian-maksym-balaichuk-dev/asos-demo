"""Demo D — dvaja WebSocket klienti dostanú potvrdenie; odpojený klient obnoví stav snapshotom."""
import asyncio
import json

import websockets

from tests.conftest import WS_URL, create_pending


async def _recv_type(ws, wanted: str, timeout=5.0) -> dict:
    async def loop():
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == wanted:
                return msg
    return await asyncio.wait_for(loop(), timeout)


async def test_two_clients_receive_confirmation(client):
    rid = (await create_pending(client))["id"]
    async with websockets.connect(WS_URL + "?client=A") as a, websockets.connect(WS_URL + "?client=B") as b:
        await _recv_type(a, "hello")
        await _recv_type(b, "hello")
        await client.post("/demo/provider/payment", json={"reservation_id": rid})
        ma, mb = await asyncio.gather(_recv_type(a, "reservation.confirmed"), _recv_type(b, "reservation.confirmed"))
        assert ma["reservation"]["id"] == mb["reservation"]["id"] == rid
        assert ma["reservation"]["status"] == "CONFIRMED"


async def test_reconnect_recovers_via_snapshot(client):
    rid = (await create_pending(client))["id"]
    ws = await websockets.connect(WS_URL + "?client=offline")
    await _recv_type(ws, "hello")
    await ws.close()                                   # klient sa odpojí
    await client.post("/demo/provider/payment", json={"reservation_id": rid})  # zmena počas výpadku
    async with websockets.connect(WS_URL + "?client=offline") as ws2:
        hello = await _recv_type(ws2, "hello")
        assert "replay" in hello["note"]               # server nesľubuje replay
        snap = (await client.get(f"/reservations/{rid}")).json()
        assert snap["status"] == "CONFIRMED"           # stav získaný zo snapshotu
        try:
            msg = await asyncio.wait_for(ws2.recv(), 0.5)
            assert json.loads(msg)["type"] != "reservation.confirmed"
        except asyncio.TimeoutError:
            pass                                       # zmeškaná správa nepríde — správne
