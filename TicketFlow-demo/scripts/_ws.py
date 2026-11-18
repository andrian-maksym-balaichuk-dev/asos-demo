"""Minimálny WebSocket klient (RFC 6455) zo štandardnej knižnice — na preflight bez pip install.

Podporuje: handshake, čítanie textových rámcov, zatvorenie. Nie je určený na produkciu.
Použitie:  ws = MiniWS("ws://localhost:8000/ws?client=A"); ws.recv_type("hello"); ws.close()
"""
import base64
import json
import os
import socket
import struct
from urllib.parse import urlparse

OPCODE_CLOSE = 0x8


class MiniWS:
    def __init__(self, url, timeout=5.0):
        parsed = urlparse(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)

        # 1. HTTP Upgrade požiadavka
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())

        # 2. čítaj hlavičky odpovede; čo prišlo za nimi, patrí už prvým rámcom
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("handshake zlyhal")
            response += chunk
        head, self._buf = response.split(b"\r\n\r\n", 1)

        # 3. server musí odpovedať 101 Switching Protocols
        status_line = head.split(b"\r\n")[0]
        if b" 101 " not in status_line:
            raise ConnectionError(status_line.decode())

    def _read(self, n):
        """Presne n bajtov zo socketu (s bufferom)."""
        while len(self._buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("spojenie zatvorené")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv_json(self):
        """Prečíta jeden rámec zo servera (server rámce nemaskuje) a dekóduje JSON."""
        first_byte, second_byte = self._read(2)
        length = second_byte & 0x7F
        if length == 126:      # 16-bitová dĺžka
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:    # 64-bitová dĺžka
            length = struct.unpack(">Q", self._read(8))[0]
        payload = self._read(length)
        if first_byte & 0x0F == OPCODE_CLOSE:
            raise ConnectionError("server zatvoril spojenie")
        return json.loads(payload.decode())

    def recv_type(self, wanted):
        """Preskakuje správy, kým nepríde správa s daným "type"."""
        while True:
            message = self.recv_json()
            if message.get("type") == wanted:
                return message

    def close(self):
        try:
            # Close rámec od klienta musí byť maskovaný (prázdny payload)
            mask = os.urandom(4)
            self.sock.sendall(bytes([0x88, 0x80]) + mask)
        finally:
            self.sock.close()
