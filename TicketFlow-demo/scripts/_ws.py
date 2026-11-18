"""Minimálny WebSocket klient (RFC 6455) zo štandardnej knižnice — na preflight bez pip install.
Podporuje: handshake, čítanie textových rámcov, zatvorenie. Nie je určený na produkciu."""
import base64
import json
import os
import socket
import struct
from urllib.parse import urlparse


class MiniWS:
    def __init__(self, url, timeout=5.0):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + ("?" + u.query if u.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("handshake zlyhal")
            resp += chunk
        head, self._buf = resp.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError(head.split(b"\r\n")[0].decode())

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("spojenie zatvorené")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv_json(self):
        b1, b2 = self._read(2)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        payload = self._read(length)
        if b1 & 0x0F == 0x8:
            raise ConnectionError("server zatvoril spojenie")
        return json.loads(payload.decode())

    def recv_type(self, wanted):
        while True:
            m = self.recv_json()
            if m.get("type") == wanted:
                return m

    def close(self):
        try:
            mask = os.urandom(4)
            self.sock.sendall(bytes([0x88, 0x80]) + mask)
        finally:
            self.sock.close()
