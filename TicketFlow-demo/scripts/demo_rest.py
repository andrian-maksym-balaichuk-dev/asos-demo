"""Demo A fallback: Idempotency-Key retry a súbeh dvoch kupujúcich.
Použitie: python3 scripts/demo_rest.py --reset"""
import argparse
import threading
import uuid

from _client import BOLD, RESET, get, line, post, title

p = argparse.ArgumentParser()
p.add_argument("--reset", action="store_true", help="pred demom resetovať dáta")
a = p.parse_args()
if a.reset:
    post("/demo/reset")
    print("Reset → A7 VOĽNÉ")

body = {"event_id": "42", "seat_id": "A7", "buyer_id": "buyer-anna"}
key = "cli-" + uuid.uuid4().hex[:8]
title(f"1) Vytvoriť rezerváciu (Idempotency-Key: {key})")
r1 = post("/reservations", body, headers={"Idempotency-Key": key})
print(f"  {r1.status} · reservation_id={r1.json.get('id')} · replayed={r1.headers.get('Idempotent-Replayed')} · {r1.cid}")

title("2) Zopakovať PRESNE ten istý request (timeout → retry)")
r2 = post("/reservations", body, headers={"Idempotency-Key": key})
print(f"  {r2.status} · reservation_id={r2.json.get('id')} · replayed={r2.headers.get('Idempotent-Replayed')} · {r2.cid}")
st = get("/demo/state?seat=A7").json
line(r1.json.get("id") == r2.json.get("id") and st["active_count"] == 1,
     f"rovnaké reservation_id, aktívne rezervácie A7 = {st['active_count']}")

title("3) Rovnaký kľúč, iný payload")
r3 = post("/reservations", {**body, "buyer_id": "buyer-boris"}, headers={"Idempotency-Key": key})
print(f"  {r3.status} {r3.json.get('code')} — {r3.json.get('detail')}")

title("4) Reset + súbeh dvoch nezávislých kupujúcich (rôzne kľúče)")
post("/demo/reset")
results = {}
barrier = threading.Barrier(2)


def buy(name):
    barrier.wait()
    results[name] = post("/reservations", {"event_id": "42", "seat_id": "A7", "buyer_id": name},
                         headers={"Idempotency-Key": f"race-{name}-{uuid.uuid4().hex[:6]}"})


ts = [threading.Thread(target=buy, args=(n,)) for n in ("buyer-anna", "buyer-boris")]
[t.start() for t in ts]
[t.join() for t in ts]
for n, r in results.items():
    print(f"  {n:12s} → {r.status} {r.json.get('id') or r.json.get('code')} · {r.cid}")
st = get("/demo/state?seat=A7").json
print(f"\n  {st['sql']};")
for row in st["active_reservations"]:
    print(f"    id={row['id']} buyer={row['buyer_id']} status={row['status']}")
codes = sorted(r.status for r in results.values())
line(codes == [201, 409] and st["active_count"] == 1, f"{BOLD}presne 1 víťaz, 1× 409{RESET}")
