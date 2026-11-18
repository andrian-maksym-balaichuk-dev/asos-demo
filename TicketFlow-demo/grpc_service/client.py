"""gRPC klient pre Inventory.CheckSeat s explicitným deadline.

CLI (v kontajneri):  python -m grpc_service.client --seat A7 --delay-ms 800 --deadline-ms 200
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

_channels: dict[str, grpc.aio.Channel] = {}


def _channel(target: str) -> grpc.aio.Channel:
    # grpc.aio kanál je viazaný na event loop → cache podľa (loop, target)
    key = f"{id(asyncio.get_running_loop())}:{target}"
    ch = _channels.get(key)
    if ch is None:
        ch = grpc.aio.insecure_channel(target)
        _channels[key] = ch
    return ch


async def check_seat(target: str, event_id: str, seat_id: str, delay_ms: int = 0,
                     deadline_ms: int | None = None, correlation_id: str | None = None) -> dict:
    stub = inventory_pb2_grpc.InventoryStub(_channel(target))
    req = inventory_pb2.SeatRequest(event_id=event_id, seat_id=seat_id, artificial_delay_ms=delay_ms)
    metadata = (("x-correlation-id", correlation_id),) if correlation_id else None
    result = {
        "target": target,
        "method": "/ticketflow.inventory.v1.Inventory/CheckSeat",
        "request": {"event_id": event_id, "seat_id": seat_id, "artificial_delay_ms": delay_ms},
        "deadline_ms": deadline_ms,
        "request_protobuf_bytes": len(req.SerializeToString()),
    }
    t0 = time.perf_counter()
    try:
        reply = await stub.CheckSeat(req, timeout=(deadline_ms / 1000) if deadline_ms else None,
                                     metadata=metadata)
        result.update({
            "ok": True, "code": "OK",
            "reply": {"event_id": reply.event_id, "seat_id": reply.seat_id, "available": reply.available,
                      "status": reply.status, "server_elapsed_ms": reply.server_elapsed_ms},
            "response_protobuf_bytes": len(reply.SerializeToString()),
        })
    except grpc.aio.AioRpcError as e:
        result.update({"ok": False, "code": e.code().name, "details": e.details()})
    result["client_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


async def health_check(target: str, timeout_s: float = 2.0) -> str:
    stub = health_pb2_grpc.HealthStub(_channel(target))
    resp = await stub.Check(health_pb2.HealthCheckRequest(service=""), timeout=timeout_s)
    return health_pb2.HealthCheckResponse.ServingStatus.Name(resp.status)


async def close_channels() -> None:
    """Zatvorí kanály patriace aktuálnemu event loopu (testy majú loop na test)."""
    prefix = f"{id(asyncio.get_running_loop())}:"
    for key in [k for k in _channels if k.startswith(prefix)]:
        await _channels.pop(key).close()


def main() -> None:
    p = argparse.ArgumentParser(description="gRPC CheckSeat klient")
    p.add_argument("--target", default=os.getenv("GRPC_TARGET", "localhost:50051"))
    p.add_argument("--event", default="42")
    p.add_argument("--seat", default="A7")
    p.add_argument("--delay-ms", type=int, default=0)
    p.add_argument("--deadline-ms", type=int, default=None)
    p.add_argument("--health", action="store_true")
    a = p.parse_args()
    if a.health:
        status = asyncio.run(health_check(a.target))
        print(status)
        raise SystemExit(0 if status == "SERVING" else 1)
    print(json.dumps(asyncio.run(check_seat(a.target, a.event, a.seat, a.delay_ms, a.deadline_ms)),
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

