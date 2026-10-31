"""Light on storage and fast: routes kept 12 hours, data clean-up settings, face print reuse,
skipping still pictures, satellite map cache limit, slim daily report."""

import time

import numpy as np

from cams import geo


def _sighting(system, pid, cam, ts, snap=None):
    return system.db.execute(
        "INSERT INTO sightings(person_id, camera_id, camera_name, first_seen, last_seen, confidence, snapshot_path) "
        "VALUES (?,?,?,?,?,?,?)", (pid, cam, "Gate", ts, ts + 5, 0.8, snap))


def _snap(system, name):
    d = system.paths.snapshots / "20260101"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(b"jpg")
    return f"20260101/{name}"


def test_routes_deleted_after_12_hours_alerts_kept(admin, system):
    pid = admin.post("/api/people", json={"full_name": "Asha Juma"}).json()["id"]
    now = time.time()
    old_snap, new_snap = _snap(system, "old.jpg"), _snap(system, "new.jpg")
    old = _sighting(system, pid, None, now - 13 * 3600, old_snap)
    new = _sighting(system, pid, None, now - 2 * 3600, new_snap)
    system.db.execute("INSERT INTO alerts(created_at, kind, message, person_id, sighting_id) VALUES (?,?,?,?,?)",
                      (now - 13 * 3600, "watchlist", "Asha seen", pid, old))
    system.purge_old()
    ids = {r["id"] for r in system.db.query("SELECT id FROM sightings")}
    assert ids == {new}
    # the alert stays (alerts have their own keep time) and keeps the sighting's picture
    a = system.db.one("SELECT * FROM alerts")
    assert a and a["sighting_id"] is None and a["snapshot_path"] == old_snap
    assert (system.paths.snapshots / old_snap).exists()
    # the route list only shows what is left
    tl = admin.get(f"/api/people/{pid}/timeline").json()
    assert [r["id"] for r in tl] == [new]


def test_keep_times_are_settings_and_zero_means_keep(admin, system):
    assert admin.get("/api/settings").json()["route_hours"] == "12"
    assert admin.put("/api/settings", json={"route_hours": "0"}).status_code == 200
    pid = admin.post("/api/people", json={"full_name": "Baraka"}).json()["id"]
    _sighting(system, pid, None, time.time() - 100 * 3600)
    system.invalidate_settings()
    system.purge_old()
    assert system.db.one("SELECT COUNT(*) AS n FROM sightings")["n"] == 1
    assert admin.put("/api/settings", json={"route_hours": "3", "alert_days": "7", "speed_mode": "fast",
                                            "min_free_gb": "2", "tiles_max_mb": "100", "recording_days": "0"}).status_code == 200
    assert admin.put("/api/settings", json={"speed_mode": "turbo"}).status_code == 400
    assert admin.put("/api/settings", json={"tiles_max_mb": "1"}).status_code == 400
    system.invalidate_settings()
    assert system.speed_mode() == "fast"
    system.purge_old()
    assert system.db.one("SELECT COUNT(*) AS n FROM sightings")["n"] == 0


def test_delete_now_and_usage(admin, system):
    pid = admin.post("/api/people", json={"full_name": "Cleo"}).json()["id"]
    snap = _snap(system, "a.jpg")
    _sighting(system, pid, None, time.time() - 60, snap)
    system.db.execute("INSERT INTO alerts(created_at, kind, message) VALUES (?,?,?)", (time.time(), "camera_offline", "x"))
    u = admin.get("/api/data/usage").json()
    assert u["routes"]["count"] == 1 and u["alerts"]["count"] == 1 and u["disk_total"] > 0
    assert admin.post("/api/data/delete", json={"kinds": []}).status_code == 400
    r = admin.post("/api/data/delete", json={"kinds": ["routes"]}).json()["deleted"]
    assert r["routes"] == 1
    assert not (system.paths.snapshots / snap).exists()
    assert system.db.one("SELECT COUNT(*) AS n FROM alerts")["n"] == 1       # only what was chosen
    admin.post("/api/data/delete", json={"kinds": ["alerts", "activity", "recordings", "map_cache"]})
    assert system.db.one("SELECT COUNT(*) AS n FROM alerts")["n"] == 0
    assert system.db.one("SELECT COUNT(*) AS n FROM people")["n"] == 1      # people are never touched


def test_tile_cache_trim_keeps_recent(tmp_path):
    tc = geo.TileCache(tmp_path / "tiles", fetch=lambda url: b"x" * 1000)
    for i in range(20):
        tc.get("imagery", 5, i, 1)
    old = tc.path("imagery", 5, 0, 1)
    import os
    os.utime(old, (1, 1))
    assert tc.size_bytes() == 20_000
    tc.trim(10_000)
    assert tc.size_bytes() <= 10_000 and not old.exists()


class _FakeEngine:
    def __init__(self):
        self.embeds = 0

    def embed(self, frame, face):
        self.embeds += 1
        face.embedding = np.ones(128, np.float32) / np.sqrt(128)
        face.quality = 0.5
        return face.embedding


def test_face_print_reused_while_face_stays(system):
    from cams.face_engine import Face

    eng = _FakeEngine()
    frame = np.zeros((10, 10, 3), np.uint8)
    mk = lambda x: Face(box=(x, 50, 80, 80), landmarks=np.zeros((5, 2)), score=0.9, raw=np.zeros(15))
    t = 1000.0
    system._face_prints(eng, 1, frame, [mk(100)], t)
    system._face_prints(eng, 1, frame, [mk(104)], t + 0.5)        # same place: reused
    assert eng.embeds == 1
    system._face_prints(eng, 1, frame, [mk(400)], t + 1.0)        # somewhere else: new print
    assert eng.embeds == 2
    system._face_prints(eng, 1, frame, [mk(402)], t + 5.0)        # too long ago: worked out again
    assert eng.embeds == 3


def test_still_pictures_are_skipped(system):
    from cams.cameras import CameraState

    class W:
        id = 7
        state = CameraState(id=7, name="Corridor", source="0", kind="usb")

    w = W()
    frame = np.full((360, 640, 3), 90, np.uint8)
    assert not system._nothing_moved(w, frame, 100.0)           # first picture is always checked
    system._last_analysis[7] = 100.0
    assert system._nothing_moved(w, frame, 101.0)               # nothing changed, nobody there
    moved = frame.copy()
    moved[100:300, 200:400] = 250
    assert not system._nothing_moved(w, moved, 101.5)           # something moved
    assert not system._nothing_moved(w, moved, 106.0)           # checked again after a few seconds anyway
