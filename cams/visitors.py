"""Visitor check-in at the gate.

The guard checks a visitor in: name, phone, who they are visiting, why, how long they
will stay, and their face (webcam, the gate camera or a photo). The visitor becomes a
temporary person in CAMS (type *Visitor*), so every camera recognises them and their
route can be followed like anyone else's.

* Places a visitor may go can be limited at check-in (for example only the
  Administration block). Seen anywhere else = alert. The access rules of buildings for
  the type *Visitor* also apply.
* Still inside after the time they said they would leave = alert, with where they were
  last seen.
* At check-out their face print is deleted at once, so CAMS stops recognising them. The
  visit itself (name, times, photo) stays in the visitor log for the number of days set
  in Settings -> Data and storage, then it is deleted too.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .system import CamsSystem

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id             INTEGER PRIMARY KEY,
    person_id      INTEGER REFERENCES people(id) ON DELETE SET NULL,
    full_name      TEXT NOT NULL,
    phone          TEXT NOT NULL DEFAULT '',
    from_where     TEXT NOT NULL DEFAULT '',     -- company, school, family of...
    id_document    TEXT NOT NULL DEFAULT '',     -- ID / licence number, if the site asks for it
    host           TEXT NOT NULL DEFAULT '',     -- who they are visiting
    host_person_id INTEGER,
    purpose        TEXT NOT NULL DEFAULT '',
    badge          TEXT NOT NULL DEFAULT '',
    allowed_areas  TEXT NOT NULL DEFAULT '[]',   -- building ids; [] = wherever visitors may go
    checked_in_at  REAL NOT NULL,
    expected_out   REAL NOT NULL,
    checked_out_at REAL,
    checked_in_by  TEXT NOT NULL DEFAULT '',
    checked_out_by TEXT NOT NULL DEFAULT '',
    overstay_alerted INTEGER NOT NULL DEFAULT 0,
    photo_path     TEXT                          -- kept after check-out for the visitor log
);
CREATE INDEX IF NOT EXISTS idx_visits_open ON visits(checked_out_at, expected_out);
"""


def _areas(v) -> list[int]:
    try:
        return [int(x) for x in json.loads(v or "[]")]
    except (ValueError, TypeError):
        return []


class Visitors:
    def __init__(self, system: "CamsSystem"):
        self.sys = system
        self.db = system.db
        with self.db.write() as c:
            c.executescript(SCHEMA)
        self.allowed: dict[int, set[int]] = {}       # person id -> buildings they may enter
        self.refresh()

    def refresh(self) -> None:
        allowed = {}
        for v in self.db.query("SELECT person_id, allowed_areas FROM visits WHERE checked_out_at IS NULL AND person_id IS NOT NULL"):
            a = _areas(v["allowed_areas"])
            if a:
                allowed[v["person_id"]] = set(a)
        self.allowed = allowed

    # ------------------------------------------------------------ check in / out
    def check_in(self, data: dict, user: str) -> dict:
        now = time.time()
        name = (data.get("full_name") or "").strip()
        if not name:
            raise ValueError("Type the visitor's name.")
        hours = float(data.get("hours") or 2)
        expected = float(data.get("expected_out") or 0) or now + hours * 3600
        if expected <= now:
            raise ValueError("The time they leave must be later than now.")
        host = (data.get("host") or "").strip()
        purpose = (data.get("purpose") or "").strip()
        pid = self.db.execute(
            "INSERT INTO people(full_name, person_code, category, group_name, notes, consent_given, consent_by, consent_date, "
            "alert_on_sight, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, (data.get("badge") or "").strip(), "visitor", "Visitors",
             f"Visiting {host or 'the site'}{': ' + purpose if purpose else ''}", 1, f"Visitor check-in by {user}",
             time.strftime("%Y-%m-%d"), 0, 1, now))
        vid = self.db.execute(
            "INSERT INTO visits(person_id, full_name, phone, from_where, id_document, host, host_person_id, purpose, badge, "
            "allowed_areas, checked_in_at, expected_out, checked_in_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, name, (data.get("phone") or "").strip(), (data.get("from_where") or "").strip(),
             (data.get("id_document") or "").strip(), host, data.get("host_person_id") or None, purpose,
             (data.get("badge") or "").strip(), json.dumps([int(x) for x in data.get("allowed_areas") or []]),
             now, expected, user))
        self.refresh()
        self.sys.reload_gallery()
        return self.get(vid)

    def check_out(self, vid: int, user: str) -> dict:
        v = self.db.one("SELECT * FROM visits WHERE id = ?", (vid,))
        if not v:
            raise LookupError("Visit not found.")
        if v["checked_out_at"]:
            return self.get(vid)
        photo = None
        if v["person_id"]:
            p = self.db.one("SELECT photo_path FROM people WHERE id = ?", (v["person_id"],))
            photo = p and p["photo_path"]
            # stop recognising them: delete the face prints, keep one photo for the visitor log
            for s in self.db.query("SELECT image_path FROM face_samples WHERE person_id = ?", (v["person_id"],)):
                if s["image_path"] and s["image_path"] != photo:
                    (self.sys.paths.enrollments / s["image_path"]).unlink(missing_ok=True)
            self.db.execute("DELETE FROM face_samples WHERE person_id = ?", (v["person_id"],))
            self.db.execute("UPDATE people SET active = 0 WHERE id = ?", (v["person_id"],))
        self.db.execute("UPDATE visits SET checked_out_at = ?, checked_out_by = ?, photo_path = ? WHERE id = ?",
                        (time.time(), user, photo, vid))
        self.refresh()
        self.sys.reload_gallery()
        return self.get(vid)

    def extend(self, vid: int, until: float) -> dict:
        if until <= time.time():
            raise ValueError("Choose a time later than now.")
        self.db.execute("UPDATE visits SET expected_out = ?, overstay_alerted = 0 WHERE id = ?", (until, vid))
        return self.get(vid)

    # ------------------------------------------------------------ reading
    def _decorate(self, v: dict) -> dict:
        v = dict(v)
        v["allowed_areas"] = _areas(v.get("allowed_areas"))
        v["inside"] = v["checked_out_at"] is None
        v["overstaying"] = v["inside"] and time.time() > v["expected_out"]
        last = None
        if v["person_id"]:
            last = self.db.one(
                "SELECT s.last_seen, s.camera_name, b.name AS building_name FROM sightings s "
                "LEFT JOIN cameras c ON c.id = s.camera_id LEFT JOIN buildings b ON b.id = c.building_id "
                "WHERE s.person_id = ? ORDER BY s.last_seen DESC LIMIT 1", (v["person_id"],))
            p = self.db.one("SELECT photo_path, (SELECT COUNT(*) FROM face_samples f WHERE f.person_id = people.id) AS faces "
                            "FROM people WHERE id = ?", (v["person_id"],))
            v["faces"] = p["faces"] if p else 0
            v["has_photo"] = bool((p and p["photo_path"]) or v.get("photo_path"))
        else:
            v["faces"], v["has_photo"] = 0, bool(v.get("photo_path"))
        v["last_seen"] = last
        return v

    def get(self, vid: int) -> dict | None:
        v = self.db.one("SELECT * FROM visits WHERE id = ?", (vid,))
        return self._decorate(v) if v else None

    def listing(self, inside_only: bool = False, since: float = 0) -> list[dict]:
        if inside_only:
            rows = self.db.query("SELECT * FROM visits WHERE checked_out_at IS NULL ORDER BY checked_in_at DESC")
        else:
            rows = self.db.query("SELECT * FROM visits WHERE checked_out_at IS NULL OR checked_in_at >= ? "
                                 "ORDER BY checked_out_at IS NOT NULL, checked_in_at DESC LIMIT 500", (since,))
        return [self._decorate(r) for r in rows]

    # ------------------------------------------------------------ rules
    def access_problem(self, person: dict | None, cam_areas: list[dict]) -> str | None:
        if not person:
            return None
        allowed = self.allowed.get(person.get("id"))
        if not allowed:
            return None
        buildings = [a for a in cam_areas if a.get("kind") == "building"] or cam_areas
        for a in buildings:
            if a["id"] not in allowed:
                return f"Visitor {person['full_name']} is in {a['name']}, outside the places they may visit"
        return None

    def check_overstays(self, now: float | None = None) -> int:
        now = now or time.time()
        n = 0
        for v in self.db.query("SELECT * FROM visits WHERE checked_out_at IS NULL AND overstay_alerted = 0 AND expected_out < ?", (now,)):
            d = self._decorate(v)
            ls = d["last_seen"]
            where = ""
            if ls:
                mins = int((now - ls["last_seen"]) // 60)
                place = ls["building_name"] or ls["camera_name"]
                where = f" Last seen at {place} {mins} min ago." if mins >= 1 else f" Seen at {place} just now."
            due = time.strftime("%H:%M", time.localtime(v["expected_out"]))
            self.sys._alert("visitor_overstay",
                            f"Visitor {v['full_name']}{' (visiting ' + v['host'] + ')' if v['host'] else ''} should have left at {due} "
                            f"and has not checked out.{where}", v["person_id"], None, None)
            self.db.execute("UPDATE visits SET overstay_alerted = 1 WHERE id = ?", (v["id"],))
            n += 1
        return n

    def purge(self, before: float) -> int:
        """Delete checked-out visits older than `before`, with their person record and photo."""
        old = self.db.query("SELECT id, person_id, photo_path FROM visits WHERE checked_out_at IS NOT NULL AND checked_out_at < ?", (before,))
        for v in old:
            if v["photo_path"]:
                (self.sys.paths.enrollments / v["photo_path"]).unlink(missing_ok=True)
            if v["person_id"]:
                for s in self.db.query("SELECT snapshot_path FROM sightings WHERE person_id = ? AND snapshot_path IS NOT NULL", (v["person_id"],)):
                    (self.sys.paths.snapshots / s["snapshot_path"]).unlink(missing_ok=True)
                self.db.execute("DELETE FROM people WHERE id = ? AND category = 'visitor' AND active = 0", (v["person_id"],))
            self.db.execute("DELETE FROM visits WHERE id = ?", (v["id"],))
        return len(old)
