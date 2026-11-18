"""Demo D — podpis: bez podpisu / zlý / starý → odmietnutý a DB bez zmeny."""
import json
import time

from app import config
from app.webhook import signing
from tests.conftest import create_pending

NOW = 1_700_000_010          # „teraz“ pre unit test (10 s po podpise)
TOLERANCE_S = 300


def test_signature_unit():
    """verify(): platný podpis prejde; zmena bajtu, iné tajomstvo, starý čas aj chýbajúca/zlá hlavička nie."""
    secret, raw = b"s3cret", b'{"a":1}'
    header = signing.build_header(secret, raw, 1_700_000_000)

    assert signing.verify(secret, raw, header, TOLERANCE_S, now=NOW).ok
    assert signing.verify(secret, raw + b" ", header, TOLERANCE_S, now=NOW).reason == "INVALID_SIGNATURE"
    assert signing.verify(b"other", raw, header, TOLERANCE_S, now=NOW).reason == "INVALID_SIGNATURE"
    assert signing.verify(secret, raw, header, TOLERANCE_S, now=1_700_001_000).reason == "STALE_TIMESTAMP"
    assert signing.verify(secret, raw, None, TOLERANCE_S).reason == "MISSING_SIGNATURE"
    assert signing.verify(secret, raw, "garbage", TOLERANCE_S).reason == "MALFORMED_SIGNATURE"


async def _status(client, rid):
    return (await client.get(f"/reservations/{rid}")).json()["status"]


async def test_rejections_do_not_change_db(client):
    """Bez podpisu 400, zlý podpis 401, starý timestamp 401 — rezervácia ostáva PENDING."""
    reservation_id = (await create_pending(client))["id"]
    for action, expected_status in [("unsigned", 400), ("bad-signature", 401), ("stale", 401)]:
        result = (await client.post(f"/demo/provider/{action}", json={"reservation_id": reservation_id})).json()
        assert result["received"]["status"] == expected_status, (action, result)
        assert await _status(client, reservation_id) == "PENDING"


async def test_valid_signature_confirms(client):
    """Platný podpis → 200 a prechod PENDING → CONFIRMED aj v DB."""
    reservation_id = (await create_pending(client))["id"]

    result = (await client.post("/demo/provider/payment", json={"reservation_id": reservation_id})).json()

    assert result["received"]["status"] == 200
    assert result["received"]["body"]["status_before"] == "PENDING"
    assert result["received"]["body"]["status_after"] == "CONFIRMED"
    assert await _status(client, reservation_id) == "CONFIRMED"


async def test_direct_post_signed_with_real_secret(client):
    """Podpisujú sa RAW bajty: rovnaký JSON inak naformátovaný → 401; pôvodné bajty → 200."""
    reservation_id = (await create_pending(client))["id"]
    raw = json.dumps({"id": "evt_directtest01", "type": "payment.succeeded", "created": int(time.time()),
                      "data": {"reservation_id": reservation_id}}).encode()
    signature_header = signing.build_header(config.WEBHOOK_SECRET.encode(), raw)
    headers = {signing.SIGNATURE_HEADER: signature_header, "Content-Type": "application/json"}

    # rovnaké body, ale JSON re-serializovaný inak → podpis nesedí (overujeme RAW bajty)
    reformatted = json.dumps(json.loads(raw), indent=2).encode()
    bad = await client.post("/webhooks/payment", content=reformatted, headers=headers)
    assert bad.status_code == 401

    ok = await client.post("/webhooks/payment", content=raw, headers=headers)
    assert ok.status_code == 200 and ok.json()["outcome"] == "CONFIRMED"
