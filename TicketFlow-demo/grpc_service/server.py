"""Demo B — gRPC server Inventory (samostatná služba, port 50051).

Spustenie (v kontajneri):  python -m grpc_service.server

Príbeh deadline / zrušenia:
    * `artificial_delay_ms` je LEN demo parameter — server pred odpoveďou čaká.
    * Deadline je vlastnosť KLIENTA. Keď vyprší skôr, klient dostane DEADLINE_EXCEEDED
      a gRPC runtime zruší RPC aj na serveri → v handleri vznikne asyncio.CancelledError.
    * Do logu zapíšeme, po koľkých ms bola práca servera prerušená.
      Skutočný čas práce servera (server_elapsed_ms) je iný pojem než deadline klienta.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from app.data.db import engine
from app.data.queries import seat_status
from grpc_service import inventory_pb2, inventory_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s grpc %(message)s")
log = logging.getLogger("ticketflow.grpc")

MAX_DELAY_MS = 5000      # strop pre umelé oneskorenie, aby demo nezablokovalo server
SERVICE_NAME = "ticketflow.inventory.v1.Inventory"


def elapsed_ms_since(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


# ════════════════════════════════════════════════════════════════════════
# 1. Implementácia služby Inventory
# ════════════════════════════════════════════════════════════════════════

class InventoryServicer(inventory_pb2_grpc.InventoryServicer):
    # ── ukážka B5 ──
    async def CheckSeat(self, request, context: grpc.aio.ServicerContext):
        started_at = time.perf_counter()
        correlation_id = dict(context.invocation_metadata()).get("x-correlation-id", "-")

        # 1. validácia vstupu (abort vyhodí výnimku → handler tu končí)
        if not request.event_id or not request.seat_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "event_id aj seat_id sú povinné")

        # 2. umelé oneskorenie (demo-only) + dotaz do DB
        delay_ms = min(request.artificial_delay_ms, MAX_DELAY_MS)
        try:
            if delay_ms:
                log.info("[%s] CheckSeat %s/%s — umelé oneskorenie %d ms", correlation_id,
                         request.event_id, request.seat_id, delay_ms)
                await asyncio.sleep(delay_ms / 1000)
            async with engine.connect() as conn:
                seat = await seat_status(conn, request.event_id, request.seat_id)
        except asyncio.CancelledError:
            # Klientov deadline vypršal (alebo klient zrušil) → runtime zrušil aj našu prácu.
            log.info("[%s] RPC zrušené po %.0f ms (klientov deadline vypršal / klient zrušil) — "
                     "práca servera nedokončená", correlation_id, elapsed_ms_since(started_at))
            raise

        # 3. neznáme sedadlo → NOT_FOUND
        if seat is None:
            await context.abort(grpc.StatusCode.NOT_FOUND,
                                f"Sedadlo {request.seat_id} pre udalosť {request.event_id} neexistuje")

        # 4. odpoveď s nameraným časom práce servera
        server_elapsed_ms = int(elapsed_ms_since(started_at))
        log.info("[%s] CheckSeat %s/%s → available=%s (%d ms)", correlation_id, seat["event_id"],
                 seat["seat_id"], seat["available"], server_elapsed_ms)
        return inventory_pb2.SeatReply(event_id=seat["event_id"], seat_id=seat["seat_id"],
                                       available=seat["available"], status=seat["status"],
                                       server_elapsed_ms=server_elapsed_ms)
    # ── /ukážka B5 ──


# ════════════════════════════════════════════════════════════════════════
# 2. Štart servera (Inventory + štandardný gRPC Health check)
# ════════════════════════════════════════════════════════════════════════

async def serve() -> None:
    port = int(os.getenv("GRPC_LISTEN_PORT", "50051"))
    server = grpc.aio.server()

    # 1. zaregistruj služby
    inventory_pb2_grpc.add_InventoryServicer_to_server(InventoryServicer(), server)
    health_servicer = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

    # 2. spusti server
    server.add_insecure_port(f"[::]:{port}")
    await server.start()

    # 3. ohlás SERVING ("" = celý server, plus konkrétna služba)
    await health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    await health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
    log.info("gRPC Inventory počúva na porte %d", port)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
