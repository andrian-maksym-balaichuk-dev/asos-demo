"""SOAP klienti pre CheckSeat.

* `raw_check_seat` — ručne zostavený Envelope cez httpx; vracia presné XML a bajty (pre dashboard).
* `zeep_check_seat` — nezávislý SOAP stack zeep načíta WSDL a zavolá operáciu (dôkaz validného kontraktu).

CLI: python -m soap_service.client --wsdl http://localhost:8000/soap?wsdl --seat A7
"""
from __future__ import annotations

import argparse
import time
from xml.sax.saxutils import escape

import httpx

SOAP_ACTION = "urn:ticketflow:inventory:v1#CheckSeat"


def build_request(event_id: str | None, seat_id: str | None) -> bytes:
    parts = []
    if event_id is not None:
        parts.append(f"      <tns:eventId>{escape(event_id)}</tns:eventId>")
    if seat_id is not None:
        parts.append(f"      <tns:seatId>{escape(seat_id)}</tns:seatId>")
    inner = "\n".join(parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
        '               xmlns:tns="urn:ticketflow:inventory:v1">\n'
        "  <soap:Body>\n"
        "    <tns:CheckSeat>\n"
        f"{inner}\n"
        "    </tns:CheckSeat>\n"
        "  </soap:Body>\n"
        "</soap:Envelope>\n"
    ).encode()


async def raw_check_seat(endpoint: str, event_id: str | None, seat_id: str | None,
                         correlation_id: str | None = None) -> dict:
    body = build_request(event_id, seat_id)
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{SOAP_ACTION}"'}
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(endpoint, content=body, headers=headers)
    return {
        "endpoint": endpoint,
        "http_status": resp.status_code,
        "is_fault": b"<soap:Fault" in resp.content or b":Fault>" in resp.content,
        "request_xml": body.decode(),
        "response_xml": resp.text,
        "request_body_bytes": len(body),
        "response_body_bytes": len(resp.content),
        "client_elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def zeep_check_seat(wsdl_url: str, event_id: str, seat_id: str) -> dict:
    from zeep import Client
    client = Client(wsdl_url)
    r = client.service.CheckSeat(eventId=event_id, seatId=seat_id)
    return {"eventId": r.eventId, "seatId": r.seatId, "available": r.available, "status": r.status}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--wsdl", default="http://localhost:8000/soap?wsdl")
    p.add_argument("--event", default="42")
    p.add_argument("--seat", default="A7")
    a = p.parse_args()
    print(zeep_check_seat(a.wsdl, a.event, a.seat))


if __name__ == "__main__":
    main()
