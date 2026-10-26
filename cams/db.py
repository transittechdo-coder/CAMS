"""SQLite storage.

One file (cams.db) holds everything except images. Every public function
opens its own short-lived connection, so it is safe to call from the camera
and recognition threads as well as from the web server.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .config import DEFAULT_SETTINGS

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer')),
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id             INTEGER PRIMARY KEY,
    full_name      TEXT NOT NULL,
    person_code    TEXT NOT NULL DEFAULT '',
    category       TEXT NOT NULL DEFAULT 'student'
                   CHECK (category IN ('student', 'staff', 'visitor', 'contractor', 'other')),
    group_name     TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    photo_path     TEXT,
    consent_given  INTEGER NOT NULL DEFAULT 0,
    consent_by     TEXT NOT NULL DEFAULT '',
    consent_date   TEXT NOT NULL DEFAULT '',
    alert_on_sight INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_people_name ON people(full_name);
CREATE INDEX IF NOT EXISTS idx_people_code ON people(person_code);

CREATE TABLE IF NOT EXISTS face_samples (
    id         INTEGER PRIMARY KEY,
    person_id  INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    angle      TEXT NOT NULL DEFAULT 'front',
    embedding  BLOB NOT NULL,
    image_path TEXT,
    quality    REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_person ON face_samples(person_id);

CREATE TABLE IF NOT EXISTS buildings (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    kind     TEXT NOT NULL DEFAULT 'building'
             CHECK (kind IN ('building', 'zone', 'gate', 'field', 'parking')),
    polygon  TEXT NOT NULL,          -- JSON [[x,y],...] in map metres
    height_m REAL NOT NULL DEFAULT 6,
    floors   INTEGER NOT NULL DEFAULT 1,
    color    TEXT NOT NULL DEFAULT '#5b8def'
);

CREATE TABLE IF NOT EXISTS cameras (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'rtsp'
                CHECK (kind IN ('usb', 'rtsp', 'http', 'file')),
    enabled     INTEGER NOT NULL DEFAULT 1,
    restricted  INTEGER NOT NULL DEFAULT 0,   -- alert on unknown faces
    building_id INTEGER REFERENCES buildings(id) ON DELETE SET NULL,
    floor       INTEGER NOT NULL DEFAULT 0,
    map_x       REAL,
    map_y       REAL,
    direction   REAL NOT NULL DEFAULT 0,      -- degrees, 0 = map north
    fov         REAL NOT NULL DEFAULT 90,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sightings (
    id            INTEGER PRIMARY KEY,
    person_id     INTEGER REFERENCES people(id) ON DELETE CASCADE,
    camera_id     INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    camera_name   TEXT NOT NULL DEFAULT '',
    first_seen    REAL NOT NULL,
    last_seen     REAL NOT NULL,
    confidence    REAL NOT NULL DEFAULT 0,
    hits          INTEGER NOT NULL DEFAULT 1,
    snapshot_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_sightings_person_time ON sightings(person_id, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_sightings_time ON sightings(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_sightings_camera ON sightings(camera_id, last_seen DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY,
    created_at   REAL NOT NULL,
    kind         TEXT NOT NULL,       -- 'watchlist' | 'unknown_restricted' | 'camera_offline'
    message      TEXT NOT NULL,
    person_id    INTEGER REFERENCES people(id) ON DELETE CASCADE,
    camera_id    INTEGER REFERENCES cameras(id) ON DELETE CASCADE,
    sighting_id  INTEGER REFERENCES sightings(id) ON DELETE CASCADE,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts(acknowledged, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY,
    ts       REAL NOT NULL,
    username TEXT NOT NULL,
    action   TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);

CREATE TABLE IF NOT EXISTS reference_photos (
    id         INTEGER PRIMARY KEY,
    person_id  INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    angle      TEXT NOT NULL,             -- back / top / any view without a usable face
    image_path TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refphotos_person ON reference_photos(person_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._write_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    # ------------------------------------------------------------ plumbing
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = self._connect()
        try:
            yield c
            c.commit()
        finally:
            c.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.conn() as c:
            yield c

    # Columns added after version 1. Old databases get them on start-up.
    MIGRATIONS = {
        "buildings": {
            "rotation": "REAL NOT NULL DEFAULT 0",
            "floor_names": "TEXT NOT NULL DEFAULT '[]'",
            # access rules: everyone | allow (only listed) | deny (listed may not enter)
            "access_mode": "TEXT NOT NULL DEFAULT 'everyone'",
            "access_categories": "TEXT NOT NULL DEFAULT '[]'",
            "access_groups": "TEXT NOT NULL DEFAULT '[]'",
            "access_people": "TEXT NOT NULL DEFAULT '[]'",
            "closed_hours": "TEXT NOT NULL DEFAULT ''",      # e.g. "18:00-06:00"
        },
        "cameras": {
            # suspicious-activity rules for this camera (JSON)
            "analytics": "TEXT NOT NULL DEFAULT '{}'",
        },
        "alerts": {
            "snapshot_path": "TEXT",
        },
    }

    def _migrate(self, c: sqlite3.Connection) -> None:
        for table, cols in self.MIGRATIONS.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        c.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))

    def init(self) -> None:
        with self.write() as c:
            c.executescript(SCHEMA)
            self._migrate(c)
            c.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            for k, v in DEFAULT_SETTINGS.items():
                c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        """Run a write statement; returns lastrowid."""
        with self.write() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    # ------------------------------------------------------------ settings
    def settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.query("SELECT key, value FROM settings")}

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default if default is not None else DEFAULT_SETTINGS.get(key)
        return row["value"]

    def set_settings(self, values: dict[str, Any]) -> None:
        with self.write() as c:
            for k, v in values.items():
                c.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, str(v)),
                )

    # ------------------------------------------------------------ audit
    def audit(self, username: str, action: str, detail: str | dict = "") -> None:
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        self.execute(
            "INSERT INTO audit_log(ts, username, action, detail) VALUES (?, ?, ?, ?)",
            (time.time(), username, action, detail),
        )

    # ------------------------------------------------------------ faces
    def add_face_sample(
        self,
        person_id: int,
        embedding: np.ndarray,
        angle: str,
        image_path: str | None,
        quality: float,
    ) -> int:
        emb = np.asarray(embedding, dtype=np.float32).reshape(-1)
        return self.execute(
            "INSERT INTO face_samples(person_id, angle, embedding, image_path, quality, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (person_id, angle, emb.tobytes(), image_path, float(quality), time.time()),
        )

    def load_gallery(self) -> tuple[np.ndarray, np.ndarray]:
        """All embeddings of active people as (person_ids[N], matrix[N, D])."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT fs.person_id, fs.embedding FROM face_samples fs "
                "JOIN people p ON p.id = fs.person_id WHERE p.active = 1"
            ).fetchall()
        if not rows:
            return np.zeros((0,), dtype=np.int64), np.zeros((0, 128), dtype=np.float32)
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        mat = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        return ids, mat
