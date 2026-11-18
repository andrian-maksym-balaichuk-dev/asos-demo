"""Demo B — gRPC kontrakt a deadline + SOAP/WSDL."""
import os

import pytest

from grpc_service.client import check_seat
from soap_service.client import raw_check_seat, zeep_check_seat
from tests.conftest import BASE_URL, create_pending

GRPC = os.getenv("GRPC_TARGET", "grpc:50051")


async def test_grpc_check_seat_typed_reply(client):
    r = await check_seat(GRPC, "42", "A7")
    assert r["ok"] and r["reply"]["available"] is True and r["reply"]["status"] == "FREE"
    await create_pending(client)
    r = await check_seat(GRPC, "42", "A7")
    assert r["reply"]["available"] is False and r["reply"]["status"] == "PENDING"


async def test_grpc_deadline_exceeded(client):
    r = await check_seat(GRPC, "42", "A7", delay_ms=800, deadline_ms=200)
    assert r["code"] == "DEADLINE_EXCEEDED"
    # klient skončil približne pri deadline, nie po 800 ms práce servera
    assert 150 <= r["client_elapsed_ms"] < 700


async def test_grpc_slow_but_within_deadline(client):
    r = await check_seat(GRPC, "42", "A7", delay_ms=100, deadline_ms=2000)
    assert r["ok"] and r["reply"]["server_elapsed_ms"] >= 100


async def test_grpc_not_found(client):
    r = await check_seat(GRPC, "42", "Z9")
    assert r["code"] == "NOT_FOUND"


async def test_wsdl_contains_check_seat(client):
    wsdl = (await client.get("/soap?wsdl")).text
    assert '<wsdl:operation name="CheckSeat">' in wsdl
    assert "soapAction=\"urn:ticketflow:inventory:v1#CheckSeat\"" in wsdl


def test_zeep_parses_wsdl_and_calls_operation():
    import httpx
    httpx.post(BASE_URL + "/demo/reset")
    r = zeep_check_seat(BASE_URL + "/soap?wsdl", "42", "A7")
    assert r == {"eventId": "42", "seatId": "A7", "available": True, "status": "FREE"}


async def test_soap_fault_for_invalid_request(client):
    r = await raw_check_seat(BASE_URL + "/soap", "42", None)
    assert r["http_status"] == 500 and r["is_fault"]
    assert "soap:Client" in r["response_xml"] and "seatId" in r["response_xml"]


async def test_soap_rejects_xxe(client):
    evil = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            b'xmlns:tns="urn:ticketflow:inventory:v1"><soap:Body><tns:CheckSeat>'
            b'<tns:eventId>42</tns:eventId><tns:seatId>&e;</tns:seatId></tns:CheckSeat></soap:Body></soap:Envelope>')
    r = await client.post("/soap", content=evil, headers={"Content-Type": "text/xml"})
    assert "root:" not in r.text
    assert r.status_code == 500
