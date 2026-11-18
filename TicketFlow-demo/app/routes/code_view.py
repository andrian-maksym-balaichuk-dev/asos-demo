"""Stránka /code — prechod skutočným kódom dema krok po kroku.

Ukážky sa čítajú ŽIVO zo zdrojových súborov. V kóde sú označené komentármi:

    # ── ukážka C3 ──
    ...kód, ktorý sa zobrazí...
    # ── /ukážka C3 ──

Takže na stránke je vždy presne ten kód, ktorý beží — nie kópia, ktorá by mohla zastarať.
Súbory sú pevný zoznam (žiadna cesta od klienta → žiadny path traversal).
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["Kód dema"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "frontend"

SOURCE_FILES = [
    "frontend/app.js",
    "app/routes/rest.py",
    "app/data/models.py",
    "app/data/db.py",
    "soap_service/inventory.wsdl",
    "soap_service/server.py",
    "grpc_service/inventory.proto",
    "grpc_service/client.py",
    "grpc_service/server.py",
    "app/graphql/endpoint.py",
    "app/graphql/schema.py",
    "app/webhook/signing.py",
    "app/webhook/receiver.py",
    "app/websocket/manager.py",
    "provider_simulator/payment_provider.py",
]

START = re.compile(r"── ukážka ([A-D]\d+) ──")
END = re.compile(r"── /ukážka ([A-D]\d+) ──")
LANGUAGE = {".py": "python", ".js": "javascript", ".proto": "proto", ".wsdl": "xml"}


def extract_snippets() -> dict[str, dict]:
    snippets: dict[str, dict] = {}
    for relative in SOURCE_FILES:
        lines = (PROJECT_ROOT / relative).read_text(encoding="utf-8").splitlines()
        open_id, first_line, buffer = None, 0, []
        for number, line in enumerate(lines, start=1):
            if (start := START.search(line)) and not END.search(line):
                open_id, first_line, buffer = start.group(1), number + 1, []
            elif (end := END.search(line)) and end.group(1) == open_id:
                snippets[open_id] = {
                    "file": relative,
                    "line_start": first_line,
                    "line_end": number - 1,
                    "language": LANGUAGE[Path(relative).suffix],
                    "code": textwrap.dedent("\n".join(buffer)).strip("\n"),
                }
                open_id = None
            elif open_id:
                buffer.append(line)
    return snippets


@router.get("/demo/code", summary="Označené ukážky kódu (pre stránku /code)")
async def code_snippets():
    return extract_snippets()


@router.get("/code", include_in_schema=False)
async def code_page():
    return FileResponse(FRONTEND / "code.html")
