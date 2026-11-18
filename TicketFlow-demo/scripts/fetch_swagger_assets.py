"""Build-time: stiahne Swagger UI assets lokálne, aby /docs fungovalo počas prezentácie OFFLINE.

Spúšťa sa v Dockerfile (python scripts/fetch_swagger_assets.py).
Ak sieť pri builde nie je, /docs použije CDN (iba fallback) — build preto nezlyhá.
"""
import pathlib
import urllib.request

VERSION = "5.17.14"
DEST = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "vendor"
ASSETS = ("swagger-ui-bundle.js", "swagger-ui.css")


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        if (DEST / name).exists():
            print("OK (už v repozitári)", name)
            continue
        url = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{VERSION}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                (DEST / name).write_bytes(response.read())
            print("OK", name)
        except Exception as error:  # noqa: BLE001 — chýbajúca sieť nesmie zhodiť build
            print("WARN: nepodarilo sa stiahnuť", name, error)


if __name__ == "__main__":
    main()
