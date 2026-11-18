"""Demo A (záloha z terminálu): Idempotency-Key retry a súbeh dvoch kupujúcich.

Spustenie:  python3 scripts/demo_rest.py --reset
"""
import argparse
import threading
import uuid

from _client import BOLD, RESET, get, line, post, title

RESERVATION = {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"}


def create_reservation(body, idempotency_key):
    return post("/reservations", body, headers={"Idempotency-Key": idempotency_key})


def print_reservation(response):
    print(f"  {response.status} · reservation_id={response.json.get('id')} · "
          f"replayed={response.headers.get('Idempotent-Replayed')} · {response.cid}")


def seat_state():
    return get("/demo/state?seat=A7").json


def race_two_buyers():
    """Dvaja kupujúci s RÔZNYMI kľúčmi štartujú naraz (Barrier) → rozhodne DB."""
    responses = {}
    barrier = threading.Barrier(2)

    def buy(buyer_id):
        barrier.wait()
        responses[buyer_id] = create_reservation({"event_id": "42", "seat_id": "A7", "buyer_id": buyer_id},
                                                 f"race-{buyer_id}-{uuid.uuid4().hex[:6]}")

    threads = [threading.Thread(target=buy, args=(buyer,)) for buyer in ("buyer-anna", "buyer-boris")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return responses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="pred demom resetovať dáta")
    args = parser.parse_args()
    if args.reset:
        post("/demo/reset")
        print("Reset → A7 VOĽNÉ")

    key = "cli-" + uuid.uuid4().hex[:8]

    # 1. prvý request
    title(f"1) Vytvoriť rezerváciu (Idempotency-Key: {key})")
    first = create_reservation(RESERVATION, key)
    print_reservation(first)

    # 2. retry s rovnakým kľúčom → server vráti uloženú odpoveď, nevytvorí druhú rezerváciu
    title("2) Zopakovať PRESNE ten istý request (timeout → retry)")
    retry = create_reservation(RESERVATION, key)
    print_reservation(retry)
    state = seat_state()
    line(first.json.get("id") == retry.json.get("id") and state["active_count"] == 1,
         f"rovnaké reservation_id, aktívne rezervácie A7 = {state['active_count']}")

    # 3. rovnaký kľúč s iným payloadom = chyba klienta
    title("3) Rovnaký kľúč, iný payload")
    mismatch = create_reservation({**RESERVATION, "buyer_id": "buyer-boris"}, key)
    print(f"  {mismatch.status} {mismatch.json.get('code')} — {mismatch.json.get('detail')}")

    # 4. súbeh: vyhrá presne jeden
    title("4) Reset + súbeh dvoch nezávislých kupujúcich (rôzne kľúče)")
    post("/demo/reset")
    responses = race_two_buyers()
    for buyer_id, response in responses.items():
        print(f"  {buyer_id:12s} → {response.status} {response.json.get('id') or response.json.get('code')} · {response.cid}")

    state = seat_state()
    print(f"\n  {state['sql']};")
    for row in state["active_reservations"]:
        print(f"    id={row['id']} buyer={row['buyer_id']} status={row['status']}")
    status_codes = sorted(response.status for response in responses.values())
    line(status_codes == [201, 409] and state["active_count"] == 1, f"{BOLD}presne 1 víťaz, 1× 409{RESET}")


if __name__ == "__main__":
    main()
