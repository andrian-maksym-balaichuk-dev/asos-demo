"""Preflight pred prezentáciou: overí služby a VŠETKY 4 scenáre, vysvetlí PASS/FAIL, na konci resetuje dáta.

Spustenie: python3 scripts/preflight.py          (len štandardná knižnica)
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


# ════════════════════════════════════════════════════════════════════════
# 1. Mini framework: Check zbiera očakávania, run() ich vypíše a uloží
# ════════════════════════════════════════════════════════════════════════

class Check:
    def __init__(self, scenario):
        self.scenario, self.items, self.evidence = scenario, [], {}

    def expect(self, ok, what, why_fail=""):
        """Zaznamená jedno očakávanie; why_fail = rada, čo robiť, ak neprejde."""
        self.items.append({"ok": bool(ok), "what": what, "why_fail": "" if ok else why_fail})
        return ok


def run(scenario, fn):
    check = Check(scenario)
    try:
        fn(check)
    except Exception as error:  # noqa: BLE001 — výnimka = FAIL scenára, nie pád celého preflightu
        check.expect(False, "scenár dobehol bez výnimky", f"{error.__class__.__name__}: {error}")

    passed = all(item["ok"] for item in check.items)
    print(f"\n{BOLD}{scenario}{RESET}  {GREEN + 'PASS' if passed else RED + 'FAIL'}{RESET}")
    for item in check.items:
        mark = f"{GREEN}✓{RESET}" if item["ok"] else f"{RED}✗{RESET}"
        print(f"  {mark} {item['what']}" + (f"\n      → {item['why_fail']}" if item["why_fail"] else ""))
    results.append({"scenario": scenario, "pass": passed, "checks": check.items, "evidence": check.evidence})


def reservation_body(buyer_id):
    return {"event_id": "42", "seat_id": "A7", "buyer_id": buyer_id}


def seat_state():
    return get("/demo/state?seat=A7").json


# ════════════════════════════════════════════════════════════════════════
# 2. Scenáre
# ════════════════════════════════════════════════════════════════════════

def services(c):
    health = get("/health/deps")
    deps = health.json or {}
    c.evidence = deps
    c.expect(health.status == 200, f"API {BASE_URL} odpovedá",
             "API nebeží: docker compose up --build -d; docker compose ps")
    c.expect(deps.get("db") == "ok", "PostgreSQL dostupná", f"db={deps.get('db')} — pozri docker compose logs db")
    c.expect(deps.get("grpc") == "SERVING", "gRPC Inventory SERVING",
             f"grpc={deps.get('grpc')} — docker compose logs grpc")
    c.expect(deps.get("provider") == "ok", "Payment provider simulátor", f"provider={deps.get('provider')}")

    swagger = get("/docs")
    c.expect(swagger.status == 200 and "swagger" in swagger.body.lower(), "Swagger UI /docs", "")
    c.expect("/static/vendor/" in swagger.body, "Swagger UI assets lokálne (funguje offline)",
             "Assets sa načítajú z CDN — bez internetu /docs nepôjde. Over frontend/vendor/.")


def demo_a(c):
    """REST: idempotentný retry, nesúlad payloadu, súbeh dvoch kupujúcich."""
    # 1. retry s rovnakým Idempotency-Key
    post("/demo/reset")
    body = reservation_body("buyer-anna")
    key = "preflight-" + uuid.uuid4().hex[:6]
    first = post("/reservations", body, headers={"Idempotency-Key": key})
    retry = post("/reservations", body, headers={"Idempotency-Key": key})
    state = seat_state()
    c.expect(first.status == 201, "vytvorenie → 201", f"dostal som {first.status}: {first.body[:150]}")
    c.expect(retry.status == 201 and retry.headers.get("Idempotent-Replayed") == "true"
             and first.json.get("id") == retry.json.get("id"), "retry s rovnakým kľúčom → rovnaké reservation_id",
             f"r1={first.json.get('id')} r2={retry.json.get('id')}")
    c.expect(state["active_count"] == 1, "po retry je v DB 1 aktívna rezervácia", f"active_count={state['active_count']}")

    # 2. rovnaký kľúč, iný payload
    mismatch = post("/reservations", {**body, "buyer_id": "x"}, headers={"Idempotency-Key": key})
    c.expect(mismatch.status == 422, "rovnaký kľúč + iný payload → 422", f"dostal som {mismatch.status}")

    # 3. súbeh: dvaja kupujúci naraz (Barrier), rôzne kľúče
    post("/demo/reset")
    race, barrier = {}, threading.Barrier(2)

    def buy(buyer_id):
        barrier.wait()
        race[buyer_id] = post("/reservations", reservation_body(buyer_id),
                              headers={"Idempotency-Key": f"pf-{buyer_id}-{uuid.uuid4().hex[:4]}"})

    threads = [threading.Thread(target=buy, args=(buyer,)) for buyer in ("buyer-anna", "buyer-boris")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    state = seat_state()
    status_codes = sorted(response.status for response in race.values())
    c.expect(status_codes == [201, 409], "súbeh: jeden 201, druhý 409", f"kódy={status_codes}")
    c.expect(state["active_count"] == 1, "súbeh: v DB presne 1 aktívna rezervácia",
             f"active_count={state['active_count']}")

    c.evidence = {"retry": {"first": first.json, "second": retry.json,
                            "replayed": retry.headers.get("Idempotent-Replayed")},
                  "mismatch": mismatch.json,
                  "race": {buyer: {"status": r.status, "body": r.json} for buyer, r in race.items()},
                  "db": state}


def demo_b(c):
    """SOAP (WSDL, odpoveď, Fault) a gRPC (OK, DEADLINE_EXCEEDED)."""
    post("/demo/reset")

    # 1. SOAP
    wsdl = get("/soap?wsdl")
    c.expect(wsdl.status == 200 and '<wsdl:operation name="CheckSeat">' in wsdl.body,
             "WSDL obsahuje operáciu CheckSeat", f"HTTP {wsdl.status}")
    soap = get("/demo/rpc/soap?seat=A7").json
    c.expect(soap["http_status"] == 200 and "<tns:available>true</tns:available>" in soap["response_xml"],
             "SOAP CheckSeat(42, A7) → available=true", soap["response_xml"][:200])
    fault = get("/demo/rpc/soap?invalid=true").json
    c.expect(fault["http_status"] == 500 and fault["is_fault"], "neplatný SOAP request → SOAP Fault",
             f"HTTP {fault['http_status']}")

    # 2. gRPC bez deadline
    grpc_ok = get("/demo/rpc/grpc?seat=A7").json
    c.expect(grpc_ok.get("code") == "OK" and grpc_ok["reply"]["available"] is True,
             "gRPC CheckSeat → OK, available=true", f"{grpc_ok.get('code')}: {grpc_ok.get('details')}")

    # 3. gRPC: server by pracoval 800 ms, klient čaká max 200 ms
    grpc_deadline = get("/demo/rpc/grpc?seat=A7&delay_ms=800&deadline_ms=200").json
    c.expect(grpc_deadline.get("code") == "DEADLINE_EXCEEDED",
             "gRPC 800 ms delay + 200 ms deadline → DEADLINE_EXCEEDED", f"dostal som {grpc_deadline.get('code')}")
    c.expect(grpc_deadline.get("client_elapsed_ms", 9999) < 700,
             f"klient skončil pri deadline ({grpc_deadline.get('client_elapsed_ms')} ms)", "klient čakal príliš dlho")

    c.evidence = {"soap": soap, "soap_fault": fault, "grpc_ok": grpc_ok, "grpc_deadline": grpc_deadline}


def demo_c(c):
    """GraphQL: rovnaký výsledok, 101 vs 2 skutočné SQL, ochrana limitom."""
    post("/demo/reset")
    query = '{ event(id: "42") { seats(limit: 100) { id price { amount currency } } } }'
    naive = post("/graphql/naive", {"query": query}).json
    batched = post("/graphql", {"query": query}).json
    naive_count = naive["extensions"]["sql"]["count"]
    batched_count = batched["extensions"]["sql"]["count"]

    c.expect(not naive.get("errors") and not batched.get("errors"), "obe query bez chýb",
             str(naive.get("errors") or batched.get("errors")))
    c.expect(naive["data"] == batched["data"] and len(batched["data"]["event"]["seats"]) == 100,
             "rovnaký JSON, 100 sedadiel", "")
    c.expect(naive_count == 101, f"naivne: {naive_count} skutočných SQL dotazov (očakávané 101)",
             "Nehovor 101 — ukáž skutočne namerané číslo a vysvetli rozdiel.")
    c.expect(batched_count == 2, f"batching: {batched_count} skutočné SQL dotazy (očakávané 2)",
             "Nehovor 2 — ukáž skutočné číslo.")

    over_limit = post("/graphql", {"query": '{ event(id: "42") { seats(limit: 500) { id } } }'}).json
    c.expect(bool(over_limit.get("errors")), "limit 500 zamietnutý", "")

    c.evidence = {"naive_count": naive_count, "batch_count": batched_count,
                  "naive_first_sql": naive["extensions"]["sql"]["statements"][:3],
                  "batch_sql": [statement["sql"][:220] for statement in batched["extensions"]["sql"]["statements"]],
                  "naive_ms": naive["extensions"]["durationMs"], "batch_ms": batched["extensions"]["durationMs"],
                  "sample": batched["data"]["event"]["seats"][:3]}


def demo_d(c):
    """Webhook (odmietnutie, potvrdenie, duplicita) + WebSocket push + reconnect snapshot."""
    # 1. rezervácia PENDING, 2 online klienti, 1 klient sa odpojí
    post("/demo/reset")
    ws_url = BASE_URL.replace("http", "ws", 1) + "/ws"
    reservation_id = post("/reservations", reservation_body("buyer-preflight")).json["id"]

    def reservation_status():
        return get(f"/reservations/{reservation_id}").json["status"]

    ws_a, ws_b = MiniWS(ws_url + "?client=pf-A"), MiniWS(ws_url + "?client=pf-B")
    ws_a.recv_type("hello")
    ws_b.recv_type("hello")
    ws_offline = MiniWS(ws_url + "?client=pf-off")
    ws_offline.recv_type("hello")
    ws_offline.close()

    # 2. neplatné webhooky → odmietnuté, stav sa nemení
    evidence = {}
    for action, expected_status in (("unsigned", 400), ("bad-signature", 401)):
        result = post(f"/demo/provider/{action}", {"reservation_id": reservation_id}).json
        evidence[action] = result["received"]
        status_now = reservation_status()
        c.expect(result["received"]["status"] == expected_status and status_now == "PENDING",
                 f"{action}: {expected_status} a stav ostal PENDING", f"{result['received']['status']} / {status_now}")

    # 3. platný podpis → CONFIRMED a push na oboch klientov
    payment = post("/demo/provider/payment", {"reservation_id": reservation_id}).json
    evidence["payment"] = payment
    c.expect(payment["received"]["body"].get("outcome") == "CONFIRMED", "platný podpis: PENDING → CONFIRMED",
             str(payment["received"]["body"])[:200])
    ws_a.sock.settimeout(5)
    ws_b.sock.settimeout(5)
    message_a = ws_a.recv_type("reservation.confirmed")
    message_b = ws_b.recv_type("reservation.confirmed")
    c.expect(message_a["reservation"]["id"] == message_b["reservation"]["id"] == reservation_id,
             "2 WebSocket klienti dostali potvrdenie", "")

    # 4. duplicitný webhook
    replay = post("/demo/provider/replay", {}).json
    evidence["replay"] = replay["received"]
    c.expect(replay["received"]["body"].get("result") == "DUPLICATE_IGNORED",
             "duplicitný webhook → DUPLICATE_IGNORED", "")

    # 5. reconnect → snapshot cez REST
    ws_offline = MiniWS(ws_url + "?client=pf-off")
    ws_offline.recv_type("hello")
    snapshot = get(f"/reservations/{reservation_id}").json
    c.expect(snapshot["status"] == "CONFIRMED", "reconnect: snapshot GET /reservations/{id} = CONFIRMED", "")
    for ws in (ws_a, ws_b, ws_offline):
        ws.close()

    c.evidence = {"reservation_id": reservation_id, **evidence, "snapshot": snapshot}


# ════════════════════════════════════════════════════════════════════════
# 3. Výstupy: JSON záznam + offline NÁHRADNÁ UKÁŽKA
# ════════════════════════════════════════════════════════════════════════

FALLBACK_CSS = """body{font:18px/1.5 Inter,system-ui,sans-serif;color:#0b1f44;background:#fff;margin:0 auto;max-width:1300px;padding:24px}
.banner{background:#fdf6e3;border:2px solid #a16207;color:#7a4a00;padding:14px 18px;border-radius:12px;font-weight:700}
section{border:1px solid #dde3ee;border-radius:12px;padding:16px 20px;margin:18px 0} li.ok{color:#15803d} li.bad{color:#b91c1c}
pre{background:#f4f6fb;padding:12px;border-radius:8px;overflow:auto;max-height:420px;font-size:13px}
img{max-width:100%;border:1px solid #dde3ee;border-radius:8px} figure{margin:20px 0}"""


def scenario_html(result):
    items = "".join(f"<li class='{'ok' if item['ok'] else 'bad'}'>{'✓' if item['ok'] else '✗'} {html.escape(item['what'])}</li>"
                    for item in result["checks"])
    evidence_json = json.dumps(result["evidence"], indent=2, ensure_ascii=False)[:12000]
    return (f"<section><h2>{html.escape(result['scenario'])} — {'PASS' if result['pass'] else 'FAIL'}</h2><ul>{items}</ul>"
            f"<details><summary>Zaznamenané dáta</summary><pre>{html.escape(evidence_json)}</pre></details></section>")


def write_fallback(started):
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. surový záznam
    (OUT / "preflight_last_run.json").write_text(json.dumps(
        {"recorded_at": started, "base_url": BASE_URL, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    # 2. HTML náhradná ukážka (výsledky + screenshoty, ak existujú)
    screenshots = sorted(path.name for path in OUT.glob("demo_*.png"))
    blocks = "".join(scenario_html(result) for result in results)
    images = "".join(f"<figure><img src='{name}' alt='{name}'><figcaption>{name}</figcaption></figure>"
                     for name in screenshots)
    (OUT / "fallback.html").write_text(f"""<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>TicketFlow — náhradná ukážka</title>
<style>{FALLBACK_CSS}</style></head><body>
<div class="banner">NÁHRADNÁ UKÁŽKA — záznam z preflight behu {html.escape(started)} proti {html.escape(BASE_URL)}.
Nie sú to živé dáta. Použi len ak živé demo zlyhá a povedz to publiku.</div>
<h1>TicketFlow API Showcase — záznam</h1>{blocks}<h2>Screenshoty</h2>{images or '<p>Žiadne — spusti python3 scripts/screenshots.py</p>'}
</body></html>""", encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════
# 4. Hlavný beh
# ════════════════════════════════════════════════════════════════════════

def main():
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{BOLD}TicketFlow preflight{RESET} · {BASE_URL} · {started}")

    # 1. služby — ak API vôbec neodpovedá, scenáre nemá zmysel spúšťať
    run("Služby a healthchecky", services)
    if not results[-1]["checks"][0]["ok"]:
        return 1

    # 2. všetky 4 scenáre
    run("Demo A — REST: retry a súbeh", demo_a)
    run("Demo B — SOAP/WSDL a gRPC deadline", demo_b)
    run("Demo C — GraphQL 101 vs 2 SQL", demo_c)
    run("Demo D — webhook, dedupe, WebSocket, reconnect", demo_d)

    # 3. reset, aby prezentácia začínala od čistého stavu
    reset = post("/demo/reset")
    print(f"\nReset po preflighte: {'OK' if reset.status == 200 else 'ZLYHAL'} (A7 VOĽNÉ, ďalšia rezervácia r-001)")

    # 4. záznam + náhradná ukážka
    write_fallback(started)
    all_passed = all(result["pass"] for result in results)
    print(f"\n{BOLD}{'VŠETKO PASS — môžeš prezentovať.' if all_passed else 'NIEČO ZLYHALO — pozri ✗ vyššie.'}{RESET}")
    print(f"Záznam: {OUT / 'preflight_last_run.json'}\nNáhradná ukážka: {OUT / 'fallback.html'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    started_at = time.time()
    exit_code = main()
    print(f"({time.time() - started_at:.1f} s)")
    sys.exit(exit_code)
