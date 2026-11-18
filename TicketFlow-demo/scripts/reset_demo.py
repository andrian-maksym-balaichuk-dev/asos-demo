"""Reset demo dát: koncert 42, 100 sedadiel, A7 VOĽNÉ, žiadne rezervácie (ďalšia bude r-001).

Spustenie:  python3 scripts/reset_demo.py
"""
import sys

from _client import BASE_URL, get, post


def main():
    reset = post("/demo/reset")
    if reset.status != 200:
        print(f"RESET ZLYHAL ({reset.status}) na {BASE_URL}: {reset.body[:200]}")
        sys.exit(1)
    state = get("/demo/state?seat=A7").json
    print(f"Reset OK · {reset.json['seats']} sedadiel · A7 = {state['seat']['status']} · "
          f"aktívne rezervácie A7 = {state['active_count']}")


if __name__ == "__main__":
    main()
