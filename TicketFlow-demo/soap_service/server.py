"""Demo B — SOAP 1.1 služba CheckSeat (document/literal), namontovaná v API na /soap.

* GET  /soap?wsdl  → zverejnená WSDL (soap_service/inventory.wsdl)
* POST /soap       → SOAP Envelope s <tns:CheckSeat>, odpoveď <tns:CheckSeatResponse>
* Chyby → SOAP Fault (faultcode soap:Client / soap:Server), HTTP 500 podľa SOAP 1.1 HTTP binding.

Server je zámerne malý a čitateľný (lxml), aby bolo vidieť, čo SOAP stack robí.
Správnosť WSDL overuje test nezávislým klientom zeep. XML parser má vypnuté
entity/DTD/sieť (ochrana proti XXE).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response
from lxml import etree

from app import config
from app.data.db import engine
from app.data.queries import seat_status

log = logging.getLogger("ticketflow.soap")
router = APIRouter(tags=["Demo B — SOAP"])

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
TNS = "urn:ticketflow:inventory:v1"
WSDL_PATH = Path(__file__).with_name("inventory.wsdl")
MAX_BODY = 32 * 1024
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                          dtd_validation=False, huge_tree=False, remove_blank_text=True)
XML_TYPE = "text/xml; charset=utf-8"


def wsdl_text() -> str:
    from xml.sax.saxutils import quoteattr
    return WSDL_PATH.read_text(encoding="utf-8").replace('"__SOAP_ADDRESS__"', quoteattr(config.SOAP_ADDRESS))


def _envelope(body_child: etree._Element) -> bytes:
    env = etree.Element(f"{{{SOAP_ENV}}}Envelope", nsmap={"soap": SOAP_ENV, "tns": TNS})
    body = etree.SubElement(env, f"{{{SOAP_ENV}}}Body")
    body.append(body_child)
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def fault(code: str, message: str, error_code: str) -> Response:
    f = etree.Element(f"{{{SOAP_ENV}}}Fault")
    etree.SubElement(f, "faultcode").text = f"soap:{code}"
    etree.SubElement(f, "faultstring").text = message
    detail = etree.SubElement(f, "detail")
    etree.SubElement(detail, f"{{{TNS}}}errorCode").text = error_code
    log.info("SOAP Fault %s: %s", error_code, message)
    return Response(_envelope(f), status_code=500, media_type=XML_TYPE)


@router.get("/soap", summary="WSDL (použi ?wsdl)", response_class=Response)
async def get_wsdl():
    return Response(wsdl_text(), media_type=XML_TYPE)


@router.post("/soap", summary="SOAP endpoint CheckSeat", response_class=Response)
async def soap_endpoint(request: Request):
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return fault("Client", "Požiadavka je príliš veľká (max 32 kB).", "PAYLOAD_TOO_LARGE")
    try:
        root = etree.fromstring(raw, _PARSER)
    except etree.XMLSyntaxError:
        return fault("Client", "Neplatné XML — nedá sa parsovať.", "MALFORMED_XML")
    if root.tag != f"{{{SOAP_ENV}}}Envelope":
        return fault("Client", "Koreňový element musí byť soap:Envelope (SOAP 1.1).", "NOT_A_SOAP_ENVELOPE")
    body = root.find(f"{{{SOAP_ENV}}}Body")
    if body is None or len(body) == 0:
        return fault("Client", "Chýba soap:Body alebo operácia.", "MISSING_BODY")
    op = body[0]
    if op.tag != f"{{{TNS}}}CheckSeat":
        return fault("Client", f"Neznáma operácia {etree.QName(op).localname}. Podporovaná: CheckSeat.",
                     "UNKNOWN_OPERATION")
    event_id = (op.findtext(f"{{{TNS}}}eventId") or "").strip()
    seat_id = (op.findtext(f"{{{TNS}}}seatId") or "").strip()
    if not event_id or not seat_id:
        missing = "eventId" if not event_id else "seatId"
        return fault("Client", f"Chýba povinný element {missing}.", "MISSING_ELEMENT")
    try:
        async with engine.connect() as conn:
            st = await seat_status(conn, event_id, seat_id)
    except Exception:  # noqa: BLE001
        log.exception("SOAP DB chyba")
        return fault("Server", "Interná chyba pri čítaní dostupnosti.", "INTERNAL")
    if st is None:
        return fault("Client", f"Sedadlo {seat_id} pre udalosť {event_id} neexistuje.", "SEAT_NOT_FOUND")
    resp = etree.Element(f"{{{TNS}}}CheckSeatResponse")
    etree.SubElement(resp, f"{{{TNS}}}eventId").text = st["event_id"]
    etree.SubElement(resp, f"{{{TNS}}}seatId").text = st["seat_id"]
    etree.SubElement(resp, f"{{{TNS}}}available").text = "true" if st["available"] else "false"
    etree.SubElement(resp, f"{{{TNS}}}status").text = st["status"]
    return Response(_envelope(resp), media_type=XML_TYPE)
