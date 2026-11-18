"""Demo D (záloha z terminálu): podpísaný webhook, neplatný podpis, duplicita, WebSocket a reconnect snapshot.

Spustenie:  python3 scripts/demo_webhook.py --all-cases
"""
import argparse

from _client import BASE_URL, get, line, post, title
from _ws import MiniWS

WS_URL = BASE_URL.replace("http", "ws", 1) + "/ws"

REJECTED_CASES = (
    ("unsigned", "Bez podpisu"),
    ("bad-signature", "Pokazený podpis"),
    ("stale", "Starý timestamp"),
)


def connect(client_name):
    """Pripojí WebSocket klienta a počká na úvodnú správu hello."""
    ws = MiniWS(WS_URL + f"?client={client_name}")
    hello = ws.recv_type("hello")
    return ws, hello


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-cases", action="store_true")
    args = parser.parse_args()
    if not args.all_cases:
        parser.print_help()
        raise SystemExit(0)

    # 1. čerstvá rezervácia v stave PENDING
    post("/demo/reset")
    reservation_id = post("/reservations",
                          {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-cli"}).json["id"]

    def reservation_status():
        return get(f"/reservations/{reservation_id}").json["status"]

    print(f"Rezervácia {reservation_id} = {reservation_status()}")

    # 2. dvaja online klienti + tretí, ktorý sa odpojí (zmešká udalosť)
    ws_a, _ = connect("cli-A")
    ws_b, _ = connect("cli-B")
    ws_offline, _ = connect("cli-offline")
    ws_offline.close()
    print("Pripojení 2 WebSocket klienti; tretí klient sa odpojil.")

    # 3. neplatné webhooky → príjemca odmietne, DB sa nezmení
    for action, label in REJECTED_CASES:
        title(label)
        status_before = reservation_status()
        result = post(f"/demo/provider/{action}", {"reservation_id": reservation_id}).json
        status_after = reservation_status()
        print(f"  príjemca: {result['received']['status']} {result['received']['body'].get('code')}")
        line(result["received"]["status"] in (400, 401) and status_before == status_after == "PENDING",
             f"stav {status_before} → {status_after} (DB nezmenená)")

    # 4. platný podpis → CONFIRMED + push cez WebSocket
    title("Platný podpis")
    result = post("/demo/provider/payment", {"reservation_id": reservation_id}).json
    print(f"  {result['sent']['headers'].get('TicketFlow-Signature', '')[:40]}…")
    receiver_body = result["received"]["body"]
    line(receiver_body.get("outcome") == "CONFIRMED",
         f"{receiver_body.get('status_before')} → {receiver_body.get('status_after')} · event {receiver_body.get('event_id')}")
    message_a = ws_a.recv_type("reservation.confirmed")
    message_b = ws_b.recv_type("reservation.confirmed")
    line(message_a["reservation"]["status"] == message_b["reservation"]["status"] == "CONFIRMED",
         "oba WebSocket klienti dostali reservation.confirmed")

    # 5. provider zopakuje tú istú udalosť → dedupe podľa event id
    title("Zopakovaný webhook (rovnaké event id)")
    result = post("/demo/provider/replay", {}).json
    receiver_body = result["received"]["body"]
    line(receiver_body.get("result") == "DUPLICATE_IGNORED",
         f"{result['received']['status']} {receiver_body.get('result')} · stav {receiver_body.get('status_after')}")

    # 6. reconnect: server udalosti neprehráva → klient si načíta snapshot cez REST
    title("Reconnect odpojeného klienta")
    ws_offline, hello = connect("cli-offline")
    snapshot = get(f"/reservations/{reservation_id}").json
    line(snapshot["status"] == "CONFIRMED",
         f"snapshot GET /reservations/{reservation_id} → {snapshot['status']} (server nerobí replay: „{hello['note']}“)")
    for ws in (ws_a, ws_b, ws_offline):
        ws.close()


if __name__ == "__main__":
    main()
