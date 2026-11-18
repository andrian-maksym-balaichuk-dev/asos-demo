"""Demo D — dvaja WebSocket klienti dostanú potvrdenie; odpojený klient obnoví stav snapshotom."""
import asyncio
import json

import websockets

from tests.conftest import WS_URL, create_pending


async def _recv_type(ws, wanted: str, timeout=5.0) -> dict:
    """Čaká na správu daného "type" (iné správy preskočí), najviac `timeout` sekúnd."""
    async def wait_for_wanted():
        while True:
            message = json.loads(await ws.recv())
            if message["type"] == wanted:
                return message
    return await asyncio.wait_for(wait_for_wanted(), timeout)


async def test_two_clients_receive_confirmation(client):
    """Po platnom webhooku server pushne reservation.confirmed OBOM pripojeným klientom."""
    reservation_id = (await create_pending(client))["id"]
    async with websockets.connect(WS_URL + "?client=A") as ws_a, websockets.connect(WS_URL + "?client=B") as ws_b:
        await _recv_type(ws_a, "hello")
        await _recv_type(ws_b, "hello")

        await client.post("/demo/provider/payment", json={"reservation_id": reservation_id})

        message_a, message_b = await asyncio.gather(_recv_type(ws_a, "reservation.confirmed"),
                                                    _recv_type(ws_b, "reservation.confirmed"))
        assert message_a["reservation"]["id"] == message_b["reservation"]["id"] == reservation_id
        assert message_a["reservation"]["status"] == "CONFIRMED"


async def test_reconnect_recovers_via_snapshot(client):
    """Zmeškanú udalosť server neprehrá; klient po reconnecte získa stav cez REST snapshot."""
    reservation_id = (await create_pending(client))["id"]

    # 1. klient sa pripojí a odpojí
    ws = await websockets.connect(WS_URL + "?client=offline")
    await _recv_type(ws, "hello")
    await ws.close()

    # 2. zmena počas výpadku
    await client.post("/demo/provider/payment", json={"reservation_id": reservation_id})

    # 3. reconnect → snapshot, žiadny replay
    async with websockets.connect(WS_URL + "?client=offline") as ws_reconnected:
        hello = await _recv_type(ws_reconnected, "hello")
        assert "replay" in hello["note"]               # server nesľubuje replay
        snapshot = (await client.get(f"/reservations/{reservation_id}")).json()
        assert snapshot["status"] == "CONFIRMED"       # stav získaný zo snapshotu
        try:
            late_message = await asyncio.wait_for(ws_reconnected.recv(), 0.5)
            assert json.loads(late_message)["type"] != "reservation.confirmed"
        except asyncio.TimeoutError:
            pass                                       # zmeškaná správa nepríde — správne
