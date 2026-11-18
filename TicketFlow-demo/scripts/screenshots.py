"""Vytvorí screenshoty všetkých scenárov cez headless Chrome (?autorun=1 prehrá skutočný scenár).

Použitie: python3 scripts/screenshots.py   (stack musí bežať; resetuje demo dáta)
Výstup:   docs/SCREENSHOTS/demo_*.png
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = os.getenv("BASE_URL", "http://localhost:8000")
OUT = Path(__file__).resolve().parent.parent / "docs" / "SCREENSHOTS"
CANDIDATES = [
    os.getenv("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or "",
]
SHOTS = [
    ("demo_A_rest.png", "?tab=A&autorun=1", 1500),
    ("demo_B_soap.png", "?tab=B&sub=soap&autorun=1", 1300),
    ("demo_B_grpc_deadline.png", "?tab=B&sub=grpc&autorun=1", 1300),
    ("demo_C_graphql.png", "?tab=C&autorun=1", 1500),
    ("demo_D_webhook_ws.png", "?tab=D&autorun=1", 1600),
]


def main() -> int:
    chrome = next((c for c in CANDIDATES if c and Path(c).exists()), None)
    if not chrome:
        print("Chrome/Chromium sa nenašiel — nastav premennú CHROME=/cesta/k/chrome")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for name, query, height in SHOTS:
        target = OUT / name
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size=1600,{height}", "--virtual-time-budget=20000",
                        f"--screenshot={target}", BASE + "/" + query],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("OK", target.relative_to(OUT.parent.parent))
    subprocess.run([sys.executable, str(Path(__file__).with_name("reset_demo.py"))], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
