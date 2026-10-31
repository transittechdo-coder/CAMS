"""Guards' phones: connect with one QR code, no typing.

* In Settings -> Phones the admin presses **Add a phone**, picks the guard (or types a
  new guard's name) and CAMS shows a QR code. The guard scans it with the CAMS Guard app
  (or the phone's camera, which opens the guard page). The phone is connected for a year:
  no address, user name or password to type.
* The QR code holds this PC's addresses and a one-time code that works for 15 minutes.
* Every connected phone is listed in Settings with when it was last seen, and can be
  disconnected with one press (for a lost phone).
* The app finds CAMS by itself when the PC's address changes: it calls out on the Wi-Fi
  ("is CAMS here?") and CAMS answers with its address (UDP port 8766).
"""

from __future__ import annotations

import json
import logging
import secrets
import socket
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .system import CamsSystem

log = logging.getLogger("cams.phones")

CODE_MINUTES = 15
CODE_USES = 3                 # the guard may scan with the browser first, then with the app
PHONE_DAYS = 365
DISCOVERY_PORT = 8766
DISCOVERY_ASK = b"CAMS?"

SCHEMA = """
CREATE TABLE IF NOT EXISTS phones (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL DEFAULT 'Phone',
    token      TEXT NOT NULL UNIQUE,          -- the phone's sign-in (also in sessions)
    created_at REAL NOT NULL,
    last_seen  REAL NOT NULL
);
"""


class Phones:
    def __init__(self, system: "CamsSystem"):
        self.sys = system
        self.db = system.db
        with self.db.write() as c:
            c.executescript(SCHEMA)
        self._codes: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}
        self._udp: threading.Thread | None = None
        self.port = 8765

    # ------------------------------------------------------------ pairing
    def new_code(self, user_id: int) -> dict:
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        with self._lock:
            now = time.time()
            self._codes = {k: v for k, v in self._codes.items() if v["expires"] > now}
            self._codes[code] = {"user_id": user_id, "expires": now + CODE_MINUTES * 60, "uses": 0}
        return {"code": code, "expires": now + CODE_MINUTES * 60}

    def pair(self, code: str, device: str) -> dict:
        code = (code or "").strip().upper()
        with self._lock:
            c = self._codes.get(code)
            if not c or c["expires"] < time.time() or c["uses"] >= CODE_USES:
                raise PermissionError("This code has expired. Ask for a new QR code on the CAMS computer.")
            c["uses"] += 1
        user = self.db.one("SELECT id, username, full_name, role FROM users WHERE id = ?", (c["user_id"],))
        if not user:
            raise PermissionError("That guard's account was deleted.")
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.db.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES (?, ?, ?)",
                        (token, user["id"], now + PHONE_DAYS * 86400))
        name = (device or "Phone").strip()[:60] or "Phone"
        pid = self.db.execute("INSERT INTO phones(user_id, name, token, created_at, last_seen) VALUES (?,?,?,?,?)",
                              (user["id"], name, token, now, now))
        return {"token": token, "phone_id": pid, "user": dict(user), "site_name": self.db.get_setting("site_name"),
                "days": PHONE_DAYS}

    def listing(self) -> list[dict]:
        rows = self.db.query("SELECT p.id, p.name, p.created_at, p.last_seen, u.username, u.full_name, u.role "
                             "FROM phones p JOIN users u ON u.id = p.user_id ORDER BY p.last_seen DESC")
        return rows

    def remove(self, phone_id: int) -> None:
        p = self.db.one("SELECT token FROM phones WHERE id = ?", (phone_id,))
        if p:
            self.db.execute("DELETE FROM sessions WHERE token = ?", (p["token"],))
            self.db.execute("DELETE FROM phones WHERE id = ?", (phone_id,))

    def touch(self, token: str) -> None:
        """Note that a phone checked in (at most once a minute)."""
        now = time.time()
        if now - self._seen.get(token, 0) < 60:
            return
        self._seen[token] = now
        self.db.execute("UPDATE phones SET last_seen = ? WHERE token = ?", (now, token))

    # ------------------------------------------------------------ "is CAMS here?"
    def start_discovery(self, port: int) -> None:
        """Answer the app's broadcast with this PC's port (only when phone access is on)."""
        self.port = port
        if self._udp:
            return
        self._udp = threading.Thread(target=self._answer, name="phone-discovery", daemon=True)
        self._udp.start()

    def _answer(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", DISCOVERY_PORT))
            s.settimeout(1.0)
        except OSError as exc:
            log.warning("Phones cannot find CAMS by themselves (port %s busy): %s", DISCOVERY_PORT, exc)
            return
        while not self.sys._stop.is_set():
            try:
                data, addr = s.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.strip() == DISCOVERY_ASK:
                reply = json.dumps({"cams": 1, "port": self.port, "site": self.db.get_setting("site_name") or ""}).encode()
                try:
                    s.sendto(reply, addr)
                except OSError:
                    pass
        s.close()
