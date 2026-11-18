"""Spoločný HTTP klient pre skripty — LEN štandardná knižnica (beží na hoste aj v kontajneri).

Použitie v skripte:  from _client import get, post, title, line
Cieľ API:            premenná BASE_URL (predvolene http://localhost:8000)
"""
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# Farby iba v termináli; NO_COLOR alebo presmerovaný výstup → bez ANSI kódov
GREEN, RED, YELLOW, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"
if os.getenv("NO_COLOR") or not os.isatty(1):
    GREEN = RED = YELLOW = BOLD = RESET = ""


# ── HTTP ─────────────────────────────────────────────────────────────────

class Resp:
    """Odpoveď: .status, .headers, .body (text), .json (alebo None), .cid (correlation ID)."""

    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body
        try:
            self.json = json.loads(body) if body else None
        except ValueError:
            self.json = None

    @property
    def cid(self):
        return self.headers.get("X-Correlation-ID", "-")


def request(method, path, body=None, headers=None, raw=None, timeout=15):
    """body = JSON objekt, raw = presné bajty. HTTP chyby (4xx/5xx) sa vracajú, nevyhadzujú."""
    request_headers = dict(headers or {})
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    http_request = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            return Resp(response.status, response.headers, response.read().decode())
    except urllib.error.HTTPError as error:
        return Resp(error.code, error.headers, error.read().decode())


def get(path, **kw):
    return request("GET", path, **kw)


def post(path, body=None, **kw):
    return request("POST", path, body=body, **kw)


# ── Výpis ────────────────────────────────────────────────────────────────

def title(text):
    print(f"\n{BOLD}== {text} =={RESET}")


def line(ok, text):
    print(f"  {GREEN + '✓' if ok else RED + '✗'}{RESET} {text}")
