"""Demo B — gRPC server Inventory (samostatná služba, port 50051).

`artificial_delay_ms` je zámerne demo-only parameter: server pred odpoveďou čaká.
Ak klientov deadline vyprší skôr, klient dostane DEADLINE_EXCEEDED a gRPC runtime
zruší RPC aj na serveri — do logu zapíšeme, po koľkých ms bola práca prerušená.
Deadline je vlastnosť KLIENTA; skutočný čas práce servera je iný pojem.
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
MAX_DELAY_MS = 5000


class InventoryServicer(inventory_pb2_grpc.InventoryServicer):
    async def CheckSeat(self, request, context: grpc.aio.ServicerContext):
        t0 = time.perf_counter()
        cid = dict(context.invocation_metadata()).get("x-correlation-id", "-")
        if not request.event_id or not request.seat_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "event_id aj seat_id sú povinné")
        delay = min(request.artificial_delay_ms, MAX_DELAY_MS)
        try:
            if delay:
                log.info("[%s] CheckSeat %s/%s — umelé oneskorenie %d ms", cid, request.event_id,
                         request.seat_id, delay)
                await asyncio.sleep(delay / 1000)
            async with engine.connect() as conn:
                st = await seat_status(conn, request.event_id, request.seat_id)
        except asyncio.CancelledError:
            log.info("[%s] RPC zrušené po %.0f ms (klientov deadline vypršal / klient zrušil) — "
                     "práca servera nedokončená", cid, (time.perf_counter() - t0) * 1000)
            raise
        if st is None:
            await context.abort(grpc.StatusCode.NOT_FOUND,
                                f"Sedadlo {request.seat_id} pre udalosť {request.event_id} neexistuje")
        elapsed = int((time.perf_counter() - t0) * 1000)
        log.info("[%s] CheckSeat %s/%s → available=%s (%d ms)", cid, st["event_id"], st["seat_id"],
                 st["available"], elapsed)
        return inventory_pb2.SeatReply(event_id=st["event_id"], seat_id=st["seat_id"],
                                       available=st["available"], status=st["status"],
                                       server_elapsed_ms=elapsed)


async def serve() -> None:
    port = int(os.getenv("GRPC_LISTEN_PORT", "50051"))
    server = grpc.aio.server()
    inventory_pb2_grpc.add_InventoryServicer_to_server(InventoryServicer(), server)
    health_servicer = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    await health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    await health_servicer.set("ticketflow.inventory.v1.Inventory", health_pb2.HealthCheckResponse.SERVING)
    log.info("gRPC Inventory počúva na porte %d", port)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
