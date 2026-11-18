"""Spoločný HTTP klient pre skripty — LEN štandardná knižnica (beží na hoste aj v kontajneri)."""
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
GREEN, RED, YELLOW, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"
if os.getenv("NO_COLOR") or not os.isatty(1):
    GREEN = RED = YELLOW = BOLD = RESET = ""


class Resp:
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
    h = dict(headers or {})
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.status, r.headers, r.read().decode())
    except urllib.error.HTTPError as e:
        return Resp(e.code, e.headers, e.read().decode())


def get(path, **kw):
    return request("GET", path, **kw)


def post(path, body=None, **kw):
    return request("POST", path, body=body, **kw)


def title(text):
    print(f"\n{BOLD}== {text} =={RESET}")


def line(ok, text):
    print(f"  {GREEN + '✓' if ok else RED + '✗'}{RESET} {text}")
