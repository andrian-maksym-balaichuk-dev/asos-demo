"""Preflight pred prezentáciou: overí služby a VŠETKY 4 scenáre, vysvetlí PASS/FAIL, na konci resetuje dáta.

Použitie:  python3 scripts/preflight.py          (len štandardná knižnica)
Výstupy:   docs/SCREENSHOTS/preflight_last_run.json — surový záznam behu
           docs/SCREENSHOTS/fallback.html            — NÁHRADNÁ UKÁŽKA zo skutočného behu (offline)
Exit code: 0 = všetko PASS, 1 = niečo zlyhalo.
"""
import html
import json
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from _client import BASE_URL, BOLD, GREEN, RED, RESET, get, post
from _ws import MiniWS

OUT = Path(__file__).resolve().parent.parent / "docs" / "SCREENSHOTS"
results: list[dict] = []


class Check:
    def __init__(self, scenario):
        self.scenario, self.items, self.evidence = scenario, [], {}

    def expect(self, ok, what, why_fail=""):
        self.items.append({"ok": bool(ok), "what": what, "why_fail": "" if ok else why_fail})
        return ok


def run(scenario, fn):
    c = Check(scenario)
    try:
        fn(c)
    except Exception as e:  # noqa: BLE001
        c.expect(False, "scenár dobehol bez výnimky", f"{e.__class__.__name__}: {e}")
    passed = all(i["ok"] for i in c.items)
    print(f"\n{BOLD}{scenario}{RESET}  {GREEN + 'PASS' if passed else RED + 'FAIL'}{RESET}")
    for i in c.items:
        mark = f"{GREEN}✓{RESET}" if i["ok"] else f"{RED}✗{RESET}"
        print(f"  {mark} {i['what']}" + (f"\n      → {i['why_fail']}" if i["why_fail"] else ""))
    results.append({"scenario": scenario, "pass": passed, "checks": c.items, "evidence": c.evidence})


def services(c):
    h = get("/health/deps")
    d = h.json or {}
    c.evidence = d
    c.expect(h.status == 200, f"API {BASE_URL} odpovedá", "API nebeží: docker compose up --build -d; docker compose ps")
    c.expect(d.get("db") == "ok", "PostgreSQL dostupná", f"db={d.get('db')} — pozri docker compose logs db")
    c.expect(d.get("grpc") == "SERVING", "gRPC Inventory SERVING", f"grpc={d.get('grpc')} — docker compose logs grpc")
    c.expect(d.get("provider") == "ok", "Payment provider simulátor", f"provider={d.get('provider')}")
    c.expect(get("/docs").status == 200 and "swagger" in get("/docs").body.lower(), "Swagger UI /docs", "")
    c.expect("/static/vendor/" in get("/docs").body, "Swagger UI assets lokálne (funguje offline)",
             "Assets sa načítajú z CDN — bez internetu /docs nepôjde. Over frontend/vendor/.")


def demo_a(c):
    post("/demo/reset")
    body = {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"}
    key = "preflight-" + uuid.uuid4().hex[:6]
    r1 = post("/reservations", body, headers={"Idempotency-Key": key})
    r2 = post("/reservations", body, headers={"Idempotency-Key": key})
    st = get("/demo/state?seat=A7").json
    c.expect(r1.status == 201, "vytvorenie → 201", f"dostal som {r1.status}: {r1.body[:150]}")
    c.expect(r2.status == 201 and r2.headers.get("Idempotent-Replayed") == "true"
             and r1.json.get("id") == r2.json.get("id"), "retry s rovnakým kľúčom → rovnaké reservation_id",
             f"r1={r1.json.get('id')} r2={r2.json.get('id')}")
    c.expect(st["active_count"] == 1, "po retry je v DB 1 aktívna rezervácia", f"active_count={st['active_count']}")
    r3 = post("/reservations", {**body, "buyer_id": "x"}, headers={"Idempotency-Key": key})
    c.expect(r3.status == 422, "rovnaký kľúč + iný payload → 422", f"dostal som {r3.status}")
    post("/demo/reset")
    out, barrier = {}, threading.Barrier(2)

    def buy(n):
        barrier.wait()
        out[n] = post("/reservations", {"event_id": "42", "seat_id": "A7", "buyer_id": n},
                      headers={"Idempotency-Key": f"pf-{n}-{uuid.uuid4().hex[:4]}"})
    ts = [threading.Thread(target=buy, args=(n,)) for n in ("buyer-anna", "buyer-boris")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    st = get("/demo/state?seat=A7").json
    codes = sorted(r.status for r in out.values())
    c.expect(codes == [201, 409], "súbeh: jeden 201, druhý 409", f"kódy={codes}")
    c.expect(st["active_count"] == 1, "súbeh: v DB presne 1 aktívna rezervácia", f"active_count={st['active_count']}")
    c.evidence = {"retry": {"first": r1.json, "second": r2.json, "replayed": r2.headers.get("Idempotent-Replayed")},
                  "mismatch": r3.json, "race": {n: {"status": r.status, "body": r.json} for n, r in out.items()},
                  "db": st}


def demo_b(c):
    post("/demo/reset")
    w = get("/soap?wsdl")
    c.expect(w.status == 200 and '<wsdl:operation name="CheckSeat">' in w.body, "WSDL obsahuje operáciu CheckSeat",
             f"HTTP {w.status}")
    s = get("/demo/rpc/soap?seat=A7").json
    c.expect(s["http_status"] == 200 and "<tns:available>true</tns:available>" in s["response_xml"],
             "SOAP CheckSeat(42, A7) → available=true", s["response_xml"][:200])
    f = get("/demo/rpc/soap?invalid=true").json
    c.expect(f["http_status"] == 500 and f["is_fault"], "neplatný SOAP request → SOAP Fault", f"HTTP {f['http_status']}")
    g = get("/demo/rpc/grpc?seat=A7").json
    c.expect(g.get("code") == "OK" and g["reply"]["available"] is True, "gRPC CheckSeat → OK, available=true",
             f"{g.get('code')}: {g.get('details')}")
    d = get("/demo/rpc/grpc?seat=A7&delay_ms=800&deadline_ms=200").json
    c.expect(d.get("code") == "DEADLINE_EXCEEDED", "gRPC 800 ms delay + 200 ms deadline → DEADLINE_EXCEEDED",
             f"dostal som {d.get('code')}")
    c.expect(d.get("client_elapsed_ms", 9999) < 700, f"klient skončil pri deadline ({d.get('client_elapsed_ms')} ms)",
             "klient čakal príliš dlho")
    c.evidence = {"soap": s, "soap_fault": f, "grpc_ok": g, "grpc_deadline": d}


def demo_c(c):
    post("/demo/reset")
    q = '{ event(id: "42") { seats(limit: 100) { id price { amount currency } } } }'
    n = post("/graphql/naive", {"query": q}).json
    b = post("/graphql", {"query": q}).json
    nc, bc = n["extensions"]["sql"]["count"], b["extensions"]["sql"]["count"]
    c.expect(not n.get("errors") and not b.get("errors"), "obe query bez chýb", str(n.get("errors") or b.get("errors")))
    c.expect(n["data"] == b["data"] and len(b["data"]["event"]["seats"]) == 100, "rovnaký JSON, 100 sedadiel", "")
    c.expect(nc == 101, f"naivne: {nc} skutočných SQL dotazov (očakávané 101)",
             "Nehovor 101 — ukáž skutočne namerané číslo a vysvetli rozdiel.")
    c.expect(bc == 2, f"batching: {bc} skutočné SQL dotazy (očakávané 2)", "Nehovor 2 — ukáž skutočné číslo.")
    lim = post("/graphql", {"query": '{ event(id: "42") { seats(limit: 500) { id } } }'}).json
    c.expect(bool(lim.get("errors")), "limit 500 zamietnutý", "")
    c.evidence = {"naive_count": nc, "batch_count": bc, "naive_first_sql": n["extensions"]["sql"]["statements"][:3],
                  "batch_sql": [s["sql"][:220] for s in b["extensions"]["sql"]["statements"]],
                  "naive_ms": n["extensions"]["durationMs"], "batch_ms": b["extensions"]["durationMs"],
                  "sample": b["data"]["event"]["seats"][:3]}


def demo_d(c):
    post("/demo/reset")
    ws_url = BASE_URL.replace("http", "ws", 1) + "/ws"
    rid = post("/reservations", {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-preflight"}).json["id"]
    status = lambda: get(f"/reservations/{rid}").json["status"]  # noqa: E731
    a, b = MiniWS(ws_url + "?client=pf-A"), MiniWS(ws_url + "?client=pf-B")
    a.recv_type("hello"), b.recv_type("hello")
    off = MiniWS(ws_url + "?client=pf-off")
    off.recv_type("hello")
    off.close()
    ev = {}
    for action, code in (("unsigned", 400), ("bad-signature", 401)):
        r = post(f"/demo/provider/{action}", {"reservation_id": rid}).json
        ev[action] = r["received"]
        c.expect(r["received"]["status"] == code and status() == "PENDING",
                 f"{action}: {code} a stav ostal PENDING", f"{r['received']['status']} / {status()}")
    ok = post("/demo/provider/payment", {"reservation_id": rid}).json
    ev["payment"] = ok
    c.expect(ok["received"]["body"].get("outcome") == "CONFIRMED", "platný podpis: PENDING → CONFIRMED",
             str(ok["received"]["body"])[:200])
    a.sock.settimeout(5), b.sock.settimeout(5)
    ma, mb = a.recv_type("reservation.confirmed"), b.recv_type("reservation.confirmed")
    c.expect(ma["reservation"]["id"] == mb["reservation"]["id"] == rid, "2 WebSocket klienti dostali potvrdenie", "")
    rp = post("/demo/provider/replay", {}).json
    ev["replay"] = rp["received"]
    c.expect(rp["received"]["body"].get("result") == "DUPLICATE_IGNORED", "duplicitný webhook → DUPLICATE_IGNORED", "")
    off = MiniWS(ws_url + "?client=pf-off")
    off.recv_type("hello")
    snap = get(f"/reservations/{rid}").json
    c.expect(snap["status"] == "CONFIRMED", "reconnect: snapshot GET /reservations/{id} = CONFIRMED", "")
    for w in (a, b, off):
        w.close()
    c.evidence = {"reservation_id": rid, **ev, "snapshot": snap}


def write_fallback(started):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "preflight_last_run.json").write_text(json.dumps(
        {"recorded_at": started, "base_url": BASE_URL, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    shots = sorted(p.name for p in OUT.glob("demo_*.png"))
    blocks = []
    for r in results:
        items = "".join(f"<li class='{'ok' if i['ok'] else 'bad'}'>{'✓' if i['ok'] else '✗'} {html.escape(i['what'])}</li>"
                        for i in r["checks"])
        blocks.append(f"<section><h2>{html.escape(r['scenario'])} — {'PASS' if r['pass'] else 'FAIL'}</h2><ul>{items}</ul>"
                      f"<details><summary>Zaznamenané dáta</summary><pre>{html.escape(json.dumps(r['evidence'], indent=2, ensure_ascii=False)[:12000])}</pre></details></section>")
    imgs = "".join(f"<figure><img src='{s}' alt='{s}'><figcaption>{s}</figcaption></figure>" for s in shots)
    (OUT / "fallback.html").write_text(f"""<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>TicketFlow — náhradná ukážka</title>
<style>body{{font:18px/1.5 Inter,system-ui,sans-serif;color:#0b1f44;background:#fff;margin:0 auto;max-width:1300px;padding:24px}}
.banner{{background:#fdf6e3;border:2px solid #a16207;color:#7a4a00;padding:14px 18px;border-radius:12px;font-weight:700}}
section{{border:1px solid #dde3ee;border-radius:12px;padding:16px 20px;margin:18px 0}} li.ok{{color:#15803d}} li.bad{{color:#b91c1c}}
pre{{background:#f4f6fb;padding:12px;border-radius:8px;overflow:auto;max-height:420px;font-size:13px}}
img{{max-width:100%;border:1px solid #dde3ee;border-radius:8px}} figure{{margin:20px 0}}</style></head><body>
<div class="banner">NÁHRADNÁ UKÁŽKA — záznam z preflight behu {html.escape(started)} proti {html.escape(BASE_URL)}.
Nie sú to živé dáta. Použi len ak živé demo zlyhá a povedz to publiku.</div>
<h1>TicketFlow API Showcase — záznam</h1>{''.join(blocks)}<h2>Screenshoty</h2>{imgs or '<p>Žiadne — spusti python3 scripts/screenshots.py</p>'}
</body></html>""", encoding="utf-8")


def main():
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{BOLD}TicketFlow preflight{RESET} · {BASE_URL} · {started}")
    run("Služby a healthchecky", services)
    if not results[-1]["checks"][0]["ok"]:
        return 1
    run("Demo A — REST: retry a súbeh", demo_a)
    run("Demo B — SOAP/WSDL a gRPC deadline", demo_b)
    run("Demo C — GraphQL 101 vs 2 SQL", demo_c)
    run("Demo D — webhook, dedupe, WebSocket, reconnect", demo_d)
    r = post("/demo/reset")
    print(f"\nReset po preflighte: {'OK' if r.status == 200 else 'ZLYHAL'} (A7 VOĽNÉ, ďalšia rezervácia r-001)")
    write_fallback(started)
    ok = all(r["pass"] for r in results)
    print(f"\n{BOLD}{'VŠETKO PASS — môžeš prezentovať.' if ok else 'NIEČO ZLYHALO — pozri ✗ vyššie.'}{RESET}")
    print(f"Záznam: {OUT / 'preflight_last_run.json'}\nNáhradná ukážka: {OUT / 'fallback.html'}")
    return 0 if ok else 1


if __name__ == "__main__":
    t = time.time()
    code = main()
    print(f"({time.time() - t:.1f} s)")
    sys.exit(code)
