"""Demo B — SOAP 1.1 služba CheckSeat (document/literal), beží v API na /soap.

    GET  /soap?wsdl   → kontrakt WSDL (soap_service/inventory.wsdl)
    POST /soap        → XML obálka <tns:CheckSeat> → odpoveď <tns:CheckSeatResponse>
    chyba             → SOAP Fault (HTTP 500, podľa SOAP 1.1)

Server je zámerne malý a čitateľný. Správnosť WSDL overuje test nezávislým klientom zeep.
"""
from __future__ import annotations

import logging
from pathlib import Path
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from lxml import etree

from app import config
from app.data.db import engine
from app.data.queries import seat_status

log = logging.getLogger("ticketflow.soap")
router = APIRouter(tags=["Demo B — SOAP"])

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
TNS = "urn:ticketflow:inventory:v1"
WSDL_FILE = Path(__file__).with_name("inventory.wsdl")
MAX_BODY_BYTES = 32 * 1024
XML = "text/xml; charset=utf-8"

# Bezpečný parser: žiadne entity, DTD ani sieť → ochrana proti XXE
SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                              dtd_validation=False, huge_tree=False, remove_blank_text=True)


# ── Príklady pre Swagger UI (/docs) ──────────────────────────────────────

EXAMPLE_REQUEST = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:tns="urn:ticketflow:inventory:v1">
  <soap:Body>
    <tns:CheckSeat>
      <tns:eventId>42</tns:eventId>
      <tns:seatId>A7</tns:seatId>
    </tns:CheckSeat>
  </soap:Body>
</soap:Envelope>"""

EXAMPLE_RESPONSE = """<?xml version='1.0' encoding='UTF-8'?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tns="urn:ticketflow:inventory:v1">
  <soap:Body>
    <tns:CheckSeatResponse>
      <tns:eventId>42</tns:eventId>
      <tns:seatId>A7</tns:seatId>
      <tns:available>true</tns:available>
      <tns:status>FREE</tns:status>
    </tns:CheckSeatResponse>
  </soap:Body>
</soap:Envelope>"""

EXAMPLE_FAULT = """<?xml version='1.0' encoding='UTF-8'?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tns="urn:ticketflow:inventory:v1">
  <soap:Body>
    <soap:Fault>
      <faultcode>soap:Client</faultcode>
      <faultstring>Chýba povinný element seatId.</faultstring>
      <detail><tns:errorCode>MISSING_ELEMENT</tns:errorCode></detail>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>"""

OPENAPI_SOAP_POST = {
    "requestBody": {
        "required": True,
        "description": "SOAP 1.1 obálka s operáciou CheckSeat. V Swagger UI klikni **Try it out → Execute**.",
        "content": {XML.split(";")[0]: {"schema": {"type": "string"}, "example": EXAMPLE_REQUEST}},
    },
    "parameters": [{
        "name": "SOAPAction", "in": "header", "required": False,
        "schema": {"type": "string", "example": '"urn:ticketflow:inventory:v1#CheckSeat"'},
    }],
    "responses": {
        "200": {"description": "CheckSeatResponse", "content": {"text/xml": {"example": EXAMPLE_RESPONSE}}},
        "500": {"description": "SOAP Fault (napr. chýba seatId, neznáme sedadlo, zlé XML)",
                "content": {"text/xml": {"example": EXAMPLE_FAULT}}},
    },
}


# ── Endpointy ────────────────────────────────────────────────────────────

@router.get("/soap", summary="WSDL kontrakt", response_class=Response,
            responses={200: {"description": "WSDL dokument", "content": {"text/xml": {}}}})
async def get_wsdl(wsdl: str | None = Query(default="", description="Stačí `/soap?wsdl`")):
    return Response(wsdl_text(), media_type=XML)


@router.post("/soap", summary="SOAP operácia CheckSeat(eventId, seatId)", response_class=Response,
             openapi_extra=OPENAPI_SOAP_POST)
async def soap_endpoint(request: Request):
    raw = await request.body()

    # 1. bezpečne načítaj XML
    if len(raw) > MAX_BODY_BYTES:
        return soap_fault("Client", "Požiadavka je príliš veľká (max 32 kB).", "PAYLOAD_TOO_LARGE")
    try:
        envelope = etree.fromstring(raw, SAFE_PARSER)
    except etree.XMLSyntaxError:
        return soap_fault("Client", "Neplatné XML — nedá sa parsovať.", "MALFORMED_XML")

    # 2. over tvar obálky a operáciu
    if envelope.tag != f"{{{SOAP_ENV}}}Envelope":
        return soap_fault("Client", "Koreňový element musí byť soap:Envelope (SOAP 1.1).", "NOT_A_SOAP_ENVELOPE")
    body = envelope.find(f"{{{SOAP_ENV}}}Body")
    if body is None or len(body) == 0:
        return soap_fault("Client", "Chýba soap:Body alebo operácia.", "MISSING_BODY")
    operation = body[0]
    if operation.tag != f"{{{TNS}}}CheckSeat":
        name = etree.QName(operation).localname
        return soap_fault("Client", f"Neznáma operácia {name}. Podporovaná: CheckSeat.", "UNKNOWN_OPERATION")

    # 3. vytiahni parametre
    event_id = (operation.findtext(f"{{{TNS}}}eventId") or "").strip()
    seat_id = (operation.findtext(f"{{{TNS}}}seatId") or "").strip()
    if not event_id or not seat_id:
        missing = "eventId" if not event_id else "seatId"
        return soap_fault("Client", f"Chýba povinný element {missing}.", "MISSING_ELEMENT")

    # 4. zisti stav sedadla v DB (rovnaký dotaz ako REST aj gRPC)
    try:
        async with engine.connect() as conn:
            seat = await seat_status(conn, event_id, seat_id)
    except Exception:  # noqa: BLE001
        log.exception("SOAP DB chyba")
        return soap_fault("Server", "Interná chyba pri čítaní dostupnosti.", "INTERNAL")
    if seat is None:
        return soap_fault("Client", f"Sedadlo {seat_id} pre udalosť {event_id} neexistuje.", "SEAT_NOT_FOUND")

    # 5. odpoveď
    return soap_response(seat)


# ── Pomocné funkcie ──────────────────────────────────────────────────────

def wsdl_text() -> str:
    return WSDL_FILE.read_text(encoding="utf-8").replace('"__SOAP_ADDRESS__"', quoteattr(config.SOAP_ADDRESS))


def soap_response(seat: dict) -> Response:
    response = etree.Element(f"{{{TNS}}}CheckSeatResponse")
    etree.SubElement(response, f"{{{TNS}}}eventId").text = seat["event_id"]
    etree.SubElement(response, f"{{{TNS}}}seatId").text = seat["seat_id"]
    etree.SubElement(response, f"{{{TNS}}}available").text = "true" if seat["available"] else "false"
    etree.SubElement(response, f"{{{TNS}}}status").text = seat["status"]
    return Response(envelope_bytes(response), media_type=XML)


def soap_fault(code: str, message: str, error_code: str) -> Response:
    fault = etree.Element(f"{{{SOAP_ENV}}}Fault")
    etree.SubElement(fault, "faultcode").text = f"soap:{code}"
    etree.SubElement(fault, "faultstring").text = message
    detail = etree.SubElement(fault, "detail")
    etree.SubElement(detail, f"{{{TNS}}}errorCode").text = error_code
    log.info("SOAP Fault %s: %s", error_code, message)
    return Response(envelope_bytes(fault), status_code=500, media_type=XML)


def envelope_bytes(body_content: etree._Element) -> bytes:
    envelope = etree.Element(f"{{{SOAP_ENV}}}Envelope", nsmap={"soap": SOAP_ENV, "tns": TNS})
    etree.SubElement(envelope, f"{{{SOAP_ENV}}}Body").append(body_content)
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8", pretty_print=True)
