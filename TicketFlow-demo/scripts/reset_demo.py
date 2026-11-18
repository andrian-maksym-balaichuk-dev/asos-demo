"""Reset demo dát: koncert 42, 100 sedadiel, A7 VOĽNÉ, žiadne rezervácie (ďalšia bude r-001)."""
import sys

from _client import BASE_URL, get, post

r = post("/demo/reset")
if r.status != 200:
    print(f"RESET ZLYHAL ({r.status}) na {BASE_URL}: {r.body[:200]}")
    sys.exit(1)
st = get("/demo/state?seat=A7").json
print(f"Reset OK · {r.json['seats']} sedadiel · A7 = {st['seat']['status']} · aktívne rezervácie A7 = {st['active_count']}")
