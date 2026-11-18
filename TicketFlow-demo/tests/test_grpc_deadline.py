"""Demo B — gRPC kontrakt a deadline + SOAP/WSDL."""
import os

import pytest

from grpc_service.client import check_seat
from soap_service.client import raw_check_seat, zeep_check_seat
from tests.conftest import BASE_URL, create_pending

GRPC = os.getenv("GRPC_TARGET", "grpc:50051")


# ── gRPC ─────────────────────────────────────────────────────────────────

async def test_grpc_check_seat_typed_reply(client):
    """Typovaná odpoveď odráža skutočný stav v DB: FREE → (rezervácia) → PENDING."""
    before = await check_seat(GRPC, "42", "A7")
    assert before["ok"] and before["reply"]["available"] is True and before["reply"]["status"] == "FREE"

    await create_pending(client)

    after = await check_seat(GRPC, "42", "A7")
    assert after["reply"]["available"] is False and after["reply"]["status"] == "PENDING"


async def test_grpc_deadline_exceeded(client):
    """Server by pracoval 800 ms, klient čaká max 200 ms → DEADLINE_EXCEEDED pri deadline."""
    result = await check_seat(GRPC, "42", "A7", delay_ms=800, deadline_ms=200)
    assert result["code"] == "DEADLINE_EXCEEDED"
    # klient skončil približne pri deadline, nie po 800 ms práce servera
    assert 150 <= result["client_elapsed_ms"] < 700


async def test_grpc_slow_but_within_deadline(client):
    """Pomalý server v rámci deadline → OK; server_elapsed_ms zahŕňa umelé oneskorenie."""
    result = await check_seat(GRPC, "42", "A7", delay_ms=100, deadline_ms=2000)
    assert result["ok"] and result["reply"]["server_elapsed_ms"] >= 100


async def test_grpc_not_found(client):
    """Neexistujúce sedadlo → štandardný gRPC status NOT_FOUND."""
    result = await check_seat(GRPC, "42", "Z9")
    assert result["code"] == "NOT_FOUND"


# ── SOAP / WSDL ──────────────────────────────────────────────────────────

async def test_wsdl_contains_check_seat(client):
    """WSDL kontrakt opisuje operáciu CheckSeat aj jej SOAPAction."""
    wsdl = (await client.get("/soap?wsdl")).text
    assert '<wsdl:operation name="CheckSeat">' in wsdl
    assert "soapAction=\"urn:ticketflow:inventory:v1#CheckSeat\"" in wsdl


def test_zeep_parses_wsdl_and_calls_operation():
    """Nezávislý SOAP stack (zeep) vie z WSDL zavolať operáciu → kontrakt je validný."""
    import httpx
    httpx.post(BASE_URL + "/demo/reset")
    reply = zeep_check_seat(BASE_URL + "/soap?wsdl", "42", "A7")
    assert reply == {"eventId": "42", "seatId": "A7", "available": True, "status": "FREE"}


async def test_soap_fault_for_invalid_request(client):
    """Chýbajúci seatId → SOAP Fault (HTTP 500, faultcode soap:Client)."""
    result = await raw_check_seat(BASE_URL + "/soap", "42", None)
    assert result["http_status"] == 500 and result["is_fault"]
    assert "soap:Client" in result["response_xml"] and "seatId" in result["response_xml"]


async def test_soap_rejects_xxe(client):
    """XXE: externá entita sa NEROZBALÍ — obsah /etc/passwd sa nesmie objaviť v odpovedi."""
    evil_envelope = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        b'xmlns:tns="urn:ticketflow:inventory:v1"><soap:Body><tns:CheckSeat>'
        b'<tns:eventId>42</tns:eventId><tns:seatId>&e;</tns:seatId></tns:CheckSeat></soap:Body></soap:Envelope>'
    )
    response = await client.post("/soap", content=evil_envelope, headers={"Content-Type": "text/xml"})
    assert "root:" not in response.text
    assert response.status_code == 500
