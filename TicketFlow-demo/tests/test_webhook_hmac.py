"""Demo D — podpis: bez podpisu / zlý / starý → odmietnutý a DB bez zmeny."""
import json
import time

from app import config
from app.webhook import signing
from tests.conftest import create_pending


def test_signature_unit():
    secret, raw = b"s3cret", b'{"a":1}'
    h = signing.build_header(secret, raw, 1_700_000_000)
    assert signing.verify(secret, raw, h, 300, now=1_700_000_010).ok
    assert signing.verify(secret, raw + b" ", h, 300, now=1_700_000_010).reason == "INVALID_SIGNATURE"
    assert signing.verify(b"other", raw, h, 300, now=1_700_000_010).reason == "INVALID_SIGNATURE"
    assert signing.verify(secret, raw, h, 300, now=1_700_001_000).reason == "STALE_TIMESTAMP"
    assert signing.verify(secret, raw, None, 300).reason == "MISSING_SIGNATURE"
    assert signing.verify(secret, raw, "garbage", 300).reason == "MALFORMED_SIGNATURE"


async def _status(client, rid):
    return (await client.get(f"/reservations/{rid}")).json()["status"]


async def test_rejections_do_not_change_db(client):
    rid = (await create_pending(client))["id"]
    for action, code in [("unsigned", 400), ("bad-signature", 401), ("stale", 401)]:
        r = (await client.post(f"/demo/provider/{action}", json={"reservation_id": rid})).json()
        assert r["received"]["status"] == code, (action, r)
        assert await _status(client, rid) == "PENDING"


async def test_valid_signature_confirms(client):
    rid = (await create_pending(client))["id"]
    r = (await client.post("/demo/provider/payment", json={"reservation_id": rid})).json()
    assert r["received"]["status"] == 200
    assert r["received"]["body"]["status_before"] == "PENDING"
    assert r["received"]["body"]["status_after"] == "CONFIRMED"
    assert await _status(client, rid) == "CONFIRMED"


async def test_direct_post_signed_with_real_secret(client):
    rid = (await create_pending(client))["id"]
    raw = json.dumps({"id": "evt_directtest01", "type": "payment.succeeded", "created": int(time.time()),
                      "data": {"reservation_id": rid}}).encode()
    hdr = signing.build_header(config.WEBHOOK_SECRET.encode(), raw)
    # rovnaké body, ale JSON re-serializovaný inak → podpis nesedí (overujeme RAW bajty)
    reformatted = json.dumps(json.loads(raw), indent=2).encode()
    bad = await client.post("/webhooks/payment", content=reformatted,
                            headers={signing.SIGNATURE_HEADER: hdr, "Content-Type": "application/json"})
    assert bad.status_code == 401
    ok = await client.post("/webhooks/payment", content=raw,
                           headers={signing.SIGNATURE_HEADER: hdr, "Content-Type": "application/json"})
    assert ok.status_code == 200 and ok.json()["outcome"] == "CONFIRMED"
