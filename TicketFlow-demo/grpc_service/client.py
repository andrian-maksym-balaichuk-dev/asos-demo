"""gRPC klient pre Inventory.CheckSeat s explicitným deadline.

Spustenie (v kontajneri):
    python -m grpc_service.client --seat A7 --delay-ms 800 --deadline-ms 200
    python -m grpc_service.client --health

Deadline nastavuje KLIENT (`timeout=`). Keď vyprší, volanie skončí kódom DEADLINE_EXCEEDED.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from grpc_service import inventory_pb2, inventory_pb2_grpc

CHECK_SEAT_METHOD = "/ticketflow.inventory.v1.Inventory/CheckSeat"


# ════════════════════════════════════════════════════════════════════════
# 1. Kanály (cache podľa event loopu)
# ════════════════════════════════════════════════════════════════════════

_channels: dict[str, grpc.aio.Channel] = {}


def _channel(target: str) -> grpc.aio.Channel:
    # grpc.aio kanál je viazaný na event loop → cache podľa (loop, target)
    key = f"{id(asyncio.get_running_loop())}:{target}"
    channel = _channels.get(key)
    if channel is None:
        channel = grpc.aio.insecure_channel(target)
        _channels[key] = channel
    return channel


async def close_channels() -> None:
    """Zatvorí kanály patriace aktuálnemu event loopu (testy majú loop na test)."""
    prefix = f"{id(asyncio.get_running_loop())}:"
    for key in [k for k in _channels if k.startswith(prefix)]:
        await _channels.pop(key).close()


# ════════════════════════════════════════════════════════════════════════
# 2. Volania RPC
# ════════════════════════════════════════════════════════════════════════

async def check_seat(target: str, event_id: str, seat_id: str, delay_ms: int = 0,
                     deadline_ms: int | None = None, correlation_id: str | None = None) -> dict:
    """Zavolá CheckSeat a vráti slovník pre dashboard (požiadavka, odpoveď/chyba, bajty, časy)."""
    stub = inventory_pb2_grpc.InventoryStub(_channel(target))
    request = inventory_pb2.SeatRequest(event_id=event_id, seat_id=seat_id, artificial_delay_ms=delay_ms)
    metadata = (("x-correlation-id", correlation_id),) if correlation_id else None
    timeout_s = (deadline_ms / 1000) if deadline_ms else None   # None = bez deadline

    result = {
        "target": target,
        "method": CHECK_SEAT_METHOD,
        "request": {"event_id": event_id, "seat_id": seat_id, "artificial_delay_ms": delay_ms},
        "deadline_ms": deadline_ms,
        "request_protobuf_bytes": len(request.SerializeToString()),
    }

    started_at = time.perf_counter()
    try:
        reply = await stub.CheckSeat(request, timeout=timeout_s, metadata=metadata)
        result.update({
            "ok": True, "code": "OK",
            "reply": {"event_id": reply.event_id, "seat_id": reply.seat_id, "available": reply.available,
                      "status": reply.status, "server_elapsed_ms": reply.server_elapsed_ms},
            "response_protobuf_bytes": len(reply.SerializeToString()),
        })
    except grpc.aio.AioRpcError as error:
        # napr. DEADLINE_EXCEEDED, NOT_FOUND, INVALID_ARGUMENT, UNAVAILABLE
        result.update({"ok": False, "code": error.code().name, "details": error.details()})
    result["client_elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 1)
    return result


async def health_check(target: str, timeout_s: float = 2.0) -> str:
    """Štandardný grpc.health.v1 Check → napr. 'SERVING'."""
    stub = health_pb2_grpc.HealthStub(_channel(target))
    response = await stub.Check(health_pb2.HealthCheckRequest(service=""), timeout=timeout_s)
    return health_pb2.HealthCheckResponse.ServingStatus.Name(response.status)


# ════════════════════════════════════════════════════════════════════════
# 3. CLI
# ════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="gRPC CheckSeat klient")
    parser.add_argument("--target", default=os.getenv("GRPC_TARGET", "localhost:50051"))
    parser.add_argument("--event", default="42")
    parser.add_argument("--seat", default="A7")
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--deadline-ms", type=int, default=None)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()

    if args.health:
        status = asyncio.run(health_check(args.target))
        print(status)
        raise SystemExit(0 if status == "SERVING" else 1)

    result = asyncio.run(check_seat(args.target, args.event, args.seat, args.delay_ms, args.deadline_ms))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
