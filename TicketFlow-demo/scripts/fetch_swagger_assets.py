"""Build-time: stiahne Swagger UI assets lokálne, aby /docs fungovalo počas prezentácie OFFLINE.
Ak sieť pri builde nie je, /docs použije CDN (iba fallback)."""
import pathlib
import urllib.request

VERSION = "5.17.14"
DEST = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "vendor"
DEST.mkdir(parents=True, exist_ok=True)
for name in ("swagger-ui-bundle.js", "swagger-ui.css"):
    if (DEST / name).exists():
        print("OK (už v repozitári)", name)
        continue
    url = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{VERSION}/{name}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            (DEST / name).write_bytes(r.read())
        print("OK", name)
    except Exception as e:  # noqa: BLE001
        print("WARN: nepodarilo sa stiahnuť", name, e)
