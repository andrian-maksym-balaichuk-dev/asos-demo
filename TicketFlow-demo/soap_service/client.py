"""SOAP klienti pre CheckSeat.

* `raw_check_seat`  — ručne zostavený Envelope cez httpx; vracia presné XML a bajty (pre dashboard).
* `zeep_check_seat` — nezávislý SOAP stack zeep načíta WSDL a zavolá operáciu (dôkaz validného kontraktu).

Spustenie:  python -m soap_service.client --wsdl http://localhost:8000/soap?wsdl --seat A7
"""
from __future__ import annotations

import argparse
import time
from xml.sax.saxutils import escape

import httpx

SOAP_ACTION = "urn:ticketflow:inventory:v1#CheckSeat"


# ════════════════════════════════════════════════════════════════════════
# 1. Ručne zostavená SOAP obálka
# ════════════════════════════════════════════════════════════════════════

def build_request(event_id: str | None, seat_id: str | None) -> bytes:
    """SOAP 1.1 obálka CheckSeat. None = element vynecháme (na ukážku SOAP Fault)."""
    parameter_lines = []
    if event_id is not None:
        parameter_lines.append(f"      <tns:eventId>{escape(event_id)}</tns:eventId>")
    if seat_id is not None:
        parameter_lines.append(f"      <tns:seatId>{escape(seat_id)}</tns:seatId>")
    parameters_xml = "\n".join(parameter_lines)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
        '               xmlns:tns="urn:ticketflow:inventory:v1">\n'
        "  <soap:Body>\n"
        "    <tns:CheckSeat>\n"
        f"{parameters_xml}\n"
        "    </tns:CheckSeat>\n"
        "  </soap:Body>\n"
        "</soap:Envelope>\n"
    ).encode()


async def raw_check_seat(endpoint: str, event_id: str | None, seat_id: str | None,
                         correlation_id: str | None = None) -> dict:
    """POST obálky cez httpx; vráti XML požiadavky/odpovede, veľkosti a čas pre dashboard."""
    body = build_request(event_id, seat_id)
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{SOAP_ACTION}"'}
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id

    started_at = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0) as http:
        response = await http.post(endpoint, content=body, headers=headers)

    return {
        "endpoint": endpoint,
        "http_status": response.status_code,
        "is_fault": b"<soap:Fault" in response.content or b":Fault>" in response.content,
        "request_xml": body.decode(),
        "response_xml": response.text,
        "request_body_bytes": len(body),
        "response_body_bytes": len(response.content),
        "client_elapsed_ms": round((time.perf_counter() - started_at) * 1000, 1),
    }


# ════════════════════════════════════════════════════════════════════════
# 2. Nezávislý klient zeep (číta iba WSDL)
# ════════════════════════════════════════════════════════════════════════

def zeep_check_seat(wsdl_url: str, event_id: str, seat_id: str) -> dict:
    from zeep import Client   # import až tu: zeep netreba pre raw klienta
    zeep_client = Client(wsdl_url)
    reply = zeep_client.service.CheckSeat(eventId=event_id, seatId=seat_id)
    return {"eventId": reply.eventId, "seatId": reply.seatId, "available": reply.available,
            "status": reply.status}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wsdl", default="http://localhost:8000/soap?wsdl")
    parser.add_argument("--event", default="42")
    parser.add_argument("--seat", default="A7")
    args = parser.parse_args()
    print(zeep_check_seat(args.wsdl, args.event, args.seat))


if __name__ == "__main__":
    main()
