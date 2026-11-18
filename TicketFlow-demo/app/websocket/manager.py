"""WebSocket: živé notifikácie po COMMITe v databáze.

Dôležité obmedzenia (zámerne a priznane):
* Server NEROBÍ replay zmeškaných správ. Klient po (re)connecte načíta aktuálny
  snapshot cez GET /reservations/{id} — databáza je zdroj pravdy.
* Zoznam spojení je v pamäti jedného procesu → API beží s 1 Uvicorn workerom.
  Pri viacerých procesoch by bol potrebný Redis pub/sub alebo podobný broker.
* WebSocket nezaručuje doručenie: odpojený klient správu jednoducho nedostane.
"""
from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.common import now_iso

log = logging.getLogger("ticketflow.ws")
router = APIRouter()
CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9 _.-]{1,40}$")
DEFAULT_CLIENT_NAME = "klient"


# ════════════════════════════════════════════════════════════════════════
# 1. Správca spojení — kto je pripojený a broadcast
# ════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[int, tuple[str, WebSocket]] = {}   # id(ws) → (meno, spojenie)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, client_name: str) -> None:
        await ws.accept()
        async with self._lock:
            self._clients[id(ws)] = (client_name, ws)
        log.info("WS pripojený: %s (spolu %d)", client_name, len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            entry = self._clients.pop(id(ws), None)
        if entry:
            log.info("WS odpojený: %s (spolu %d)", entry[0], len(self._clients))

    def client_names(self) -> list[str]:
        return [name for name, _ in self._clients.values()]

    # ── ukážka D9 ──
    async def broadcast(self, message: dict) -> int:
        """Pošle správu všetkým pripojeným klientom. Vracia počet úspešných odoslaní."""
        message = {"sent_at": now_iso(), **message}
        # kópia zoznamu: posielanie je pomalé, zámok nedržíme počas await send
        async with self._lock:
            targets = list(self._clients.items())

        delivered = 0
        for key, (name, ws) in targets:
            try:
                await ws.send_json(message)
                delivered += 1
            except Exception:  # noqa: BLE001 — mŕtve spojenie odstránime
                async with self._lock:
                    self._clients.pop(key, None)
                log.info("WS klient %s nedostupný, odstránený", name)
        return delivered
    # ── /ukážka D9 ──


manager = ConnectionManager()


# ════════════════════════════════════════════════════════════════════════
# 2. Endpoint /ws
# ════════════════════════════════════════════════════════════════════════

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, client: str = DEFAULT_CLIENT_NAME):
    name = client if CLIENT_NAME_RE.match(client) else DEFAULT_CLIENT_NAME
    await manager.connect(ws, name)
    try:
        # 1. uvítanie — pripomenie klientovi, že stav si má načítať sám
        await ws.send_json({
            "type": "hello",
            "client": name,
            "connected_clients": len(manager.client_names()),
            "sent_at": now_iso(),
            "note": "Server nerobí replay. Aktuálny stav načítaj cez GET /reservations/{id}.",
        })
        # 2. drž spojenie otvorené; klient môže posielať "ping"
        while True:
            incoming = await ws.receive_text()
            if incoming == "ping":
                await ws.send_json({"type": "pong", "sent_at": now_iso()})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
