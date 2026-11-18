"""Demo D fallback: podpísaný webhook, neplatný podpis, duplicita, WebSocket a reconnect snapshot.
Použitie: python3 scripts/demo_webhook.py --all-cases"""
import argparse

from _client import BASE_URL, get, line, post, title
from _ws import MiniWS

p = argparse.ArgumentParser()
p.add_argument("--all-cases", action="store_true")
a = p.parse_args()
if not a.all_cases:
    p.print_help()
    raise SystemExit(0)

WS = BASE_URL.replace("http", "ws", 1) + "/ws"
post("/demo/reset")
rid = post("/reservations", {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-cli"}).json["id"]
status = lambda: get(f"/reservations/{rid}").json["status"]  # noqa: E731
print(f"Rezervácia {rid} = {status()}")

ws_a, ws_b = MiniWS(WS + "?client=cli-A"), MiniWS(WS + "?client=cli-B")
ws_a.recv_type("hello"), ws_b.recv_type("hello")
ws_off = MiniWS(WS + "?client=cli-offline")
ws_off.recv_type("hello")
ws_off.close()
print("Pripojení 2 WebSocket klienti; tretí klient sa odpojil.")

for action, label in (("unsigned", "Bez podpisu"), ("bad-signature", "Pokazený podpis"), ("stale", "Starý timestamp")):
    title(label)
    before = status()
    r = post(f"/demo/provider/{action}", {"reservation_id": rid}).json
    after = status()
    print(f"  príjemca: {r['received']['status']} {r['received']['body'].get('code')}")
    line(r["received"]["status"] in (400, 401) and before == after == "PENDING", f"stav {before} → {after} (DB nezmenená)")

title("Platný podpis")
r = post("/demo/provider/payment", {"reservation_id": rid}).json
print(f"  {r['sent']['headers'].get('TicketFlow-Signature', '')[:40]}…")
b = r["received"]["body"]
line(b.get("outcome") == "CONFIRMED", f"{b.get('status_before')} → {b.get('status_after')} · event {b.get('event_id')}")
ma, mb = ws_a.recv_type("reservation.confirmed"), ws_b.recv_type("reservation.confirmed")
line(ma["reservation"]["status"] == mb["reservation"]["status"] == "CONFIRMED", "oba WebSocket klienti dostali reservation.confirmed")

title("Zopakovaný webhook (rovnaké event id)")
r = post("/demo/provider/replay", {}).json
b = r["received"]["body"]
line(b.get("result") == "DUPLICATE_IGNORED", f"{r['received']['status']} {b.get('result')} · stav {b.get('status_after')}")

title("Reconnect odpojeného klienta")
ws_off = MiniWS(WS + "?client=cli-offline")
hello = ws_off.recv_type("hello")
snap = get(f"/reservations/{rid}").json
line(snap["status"] == "CONFIRMED", f"snapshot GET /reservations/{rid} → {snap['status']} (server nerobí replay: „{hello['note']}“)")
for w in (ws_a, ws_b, ws_off):
    w.close()
