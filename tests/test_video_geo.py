"""Satellite map + GPS position, camera recordings, sighting clips, mouse setting."""

import time

import cv2
import numpy as np
import pytest

from cams import geo
from conftest import sample


def _jpg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


# ---------------------------------------------------------------- geo
def test_parse_location_formats():
    assert geo.parse_location("-6.7701, 39.2405") == (-6.7701, 39.2405)
    assert geo.parse_location("https://www.google.com/maps/@-6.7631,39.2433,17z") == (-6.7631, 39.2433)
    assert geo.parse_location("https://maps.google.com/?q=-6.80,39.28") == (-6.8, 39.28)
    assert geo.parse_location("https://www.google.com/maps/place/X/data=!3d-6.77!4d39.24") == (-6.77, 39.24)
    assert geo.parse_location("https://www.openstreetmap.org/#map=18/-6.7712/39.2401") == (-6.7712, 39.2401)
    assert geo.parse_location("6.77 S 39.24 E") == (-6.77, 39.24)
    assert geo.parse_location("Mikocheni") is None
    assert geo.parse_location("95, 10") is None


def test_georef_round_trip_and_scale():
    g = geo.Georef(-6.7701, 39.2405, 300, 200)
    assert g.to_latlng(150, 100) == pytest.approx((-6.7701, 39.2405), abs=1e-7)
    lat, lng = g.to_latlng(250, 100)               # 100 m east of the centre
    assert lat == pytest.approx(-6.7701, abs=1e-6) and lng > 39.2405
    x, y = g.to_map(lat, lng)
    assert (x, y) == pytest.approx((250, 100), abs=0.01)
    # 100 m east is ~0.000905 degrees of longitude at 6.77 S
    assert (lng - 39.2405) * 111320 * np.cos(np.radians(6.7701)) == pytest.approx(100, rel=0.01)
    lat2, _ = g.to_latlng(150, 0)                  # top edge is north
    assert lat2 > -6.7701


def _fake_tiles(url):
    # a solid colour per tile so stitching mistakes would show
    z, y, x = (int(v) for v in url.rstrip("/").split("/")[-3:])
    img = np.full((256, 256, 3), ((x * 37) % 255, (y * 59) % 255, z * 10), np.uint8)
    return _jpg(img)


def test_satellite_picture_and_api(admin, system, monkeypatch):
    calls = []
    system.tiles._fetch = lambda url: calls.append(url) or _fake_tiles(url)
    img, info = geo.satellite_picture(system.tiles, -6.7701, 39.2405, 300, 200)
    assert info["zoom"] == 19 and info["missing"] == 0
    assert abs(img.shape[1] / img.shape[0] - 1.5) < 0.02
    n = len(calls)
    geo.satellite_picture(system.tiles, -6.7701, 39.2405, 300, 200)
    assert len(calls) == n, "tiles are cached on disk and not downloaded twice"

    # a building drawn before the satellite picture stays in the middle of the new map
    admin.post("/api/buildings", json={"name": "Hall", "polygon": [[90, 65], [110, 65], [110, 85], [90, 85]]})
    r = admin.post("/api/geo/satellite", json={"lat": -6.7701, "lng": 39.2405, "width_m": 300, "height_m": 200})
    assert r.status_code == 200, r.text
    m = admin.get("/api/map").json()
    assert m["width_m"] == 300 and m["geo"] == {"lat": -6.7701, "lng": 39.2405}
    assert m["image"] and "Esri" in m["attribution"]
    assert m["buildings"][0]["polygon"][0] == [140, 90]
    assert admin.get(m["image"]).status_code == 200
    # tile proxy for the location picker
    t = admin.get("/api/geo/tiles/imagery/19/322398/271230")
    assert t.status_code == 200 and t.headers["content-type"] == "image/jpeg"
    assert admin.get("/api/geo/tiles/nope/1/0/0").status_code == 404
    assert admin.get("/api/geo/parse", params={"text": "-6.7, 39.2"}).json() == {"lat": -6.7, "lng": 39.2}
    assert admin.get("/api/geo/search", params={"q": "-6.7, 39.2"}).json()[0]["lat"] == -6.7

    # no internet: a clear message instead of a broken map
    system.tiles._fetch = lambda url: None
    bad = admin.post("/api/geo/satellite", json={"lat": 10.0, "lng": 10.0, "width_m": 100, "height_m": 100})
    assert bad.status_code == 503 and "internet" in bad.json()["error"]

    assert admin.put("/api/geo", json={"lat": None, "lng": None}).status_code == 200
    assert admin.get("/api/map").json()["geo"] is None


def test_map_mouse_setting_for_every_user(admin):
    admin.post("/api/users", json={"username": "guard", "password": "guard1234", "role": "viewer"})
    admin.post("/api/logout")
    admin.post("/api/login", json={"username": "guard", "password": "guard1234"})
    assert admin.put("/api/settings", json={"map_mouse": "swapped"}).status_code == 200
    assert admin.get("/api/status").json()["map_mouse"] == "swapped"
    assert admin.put("/api/settings", json={"map_mouse": "upside"}).status_code == 400
    assert admin.put("/api/settings", json={"recording_days": 3}).status_code == 403


# ---------------------------------------------------------------- video
def _scene_video(path, face=None, frames=60):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (960, 540))
    for i in range(frames):
        bg = np.full((540, 960, 3), 60, np.uint8)
        cv2.putText(bg, str(i), (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        if face is not None:
            x = 100 + (i % 40) * 5
            bg[10:522, x:x + 512] = face
        vw.write(bg)
    vw.release()


def _wait(fn, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.3)
    return None


def test_record_download_and_export_part(admin, system, tmp_path):
    vid = tmp_path / "yard.avi"
    _scene_video(vid)
    cid = admin.post("/api/cameras", json={"name": "Yard", "source": str(vid)}).json()["id"]
    assert _wait(lambda: system.camera_status(cid)["status"] == "online")
    t0 = time.time()
    r = admin.post(f"/api/cameras/{cid}/record", json={"action": "start"})
    assert r.status_code == 200 and r.json()["recording"]
    assert admin.get("/api/cameras").json()[0]["recording"].get("manual")
    time.sleep(3.5)
    admin.post(f"/api/cameras/{cid}/record", json={"action": "stop"})
    t1 = time.time()
    recs = admin.get("/api/recordings", params={"camera_id": cid}).json()
    assert len(recs) == 1
    rec = recs[0]
    assert rec["status"] == "done" and rec["kind"] == "manual" and 2.5 < rec["duration"] < 5
    assert rec["frames"] >= 20 and rec["size_bytes"] > 0

    d = admin.get(f"/api/recordings/{rec['id']}/download")
    assert d.status_code == 200 and len(d.content) == rec["size_bytes"]
    f = admin.get(f"/api/recordings/{rec['id']}/frame.jpg", params={"t": 1})
    assert f.status_code == 200 and f.content[:2] == b"\xff\xd8"
    # the player stream sends JPEG pictures
    with admin.stream("GET", f"/api/recordings/{rec['id']}/play", params={"speed": 8}) as s:
        first = next(s.iter_bytes())
        assert b"image/jpeg" in first

    cov = admin.get(f"/api/cameras/{cid}/coverage", params={"since": t0 - 60, "until": t1 + 60}).json()
    assert len(cov) == 1 and cov[0][1] - cov[0][0] > 2.5

    # a part from the middle of the recording
    a = rec["start_ts"] + 1
    e = admin.get(f"/api/cameras/{cid}/export", params={"start": a, "end": a + 1.5})
    assert e.status_code == 200 and e.headers["content-disposition"].startswith("attachment")
    out = tmp_path / "part.mp4"
    out.write_bytes(e.content)
    cap = cv2.VideoCapture(str(out))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert abs(n - 1.5 * rec["fps"]) <= 2
    assert not list((system.paths.exports).glob("*/*")), "export temp files are cleaned up"
    nothing = admin.get(f"/api/cameras/{cid}/export", params={"start": t0 - 7200, "end": t0 - 3600})
    assert nothing.status_code == 404
    assert admin.get(f"/api/cameras/{cid}/export", params={"start": a, "end": a - 5}).status_code == 400

    assert admin.patch(f"/api/recordings/{rec['id']}", json={"keep": True}).status_code == 200
    assert admin.get(f"/api/recordings/{rec['id']}").json()["keep"] == 1
    assert admin.delete(f"/api/recordings/{rec['id']}").status_code == 200
    assert admin.get("/api/recordings", params={"camera_id": cid}).json() == []


def test_record_all_the_time(admin, system, tmp_path):
    vid = tmp_path / "gate.avi"
    _scene_video(vid)
    cid = admin.post("/api/cameras", json={"name": "Gate", "source": str(vid), "record_mode": "always"}).json()["id"]
    assert _wait(lambda: system.recorder.active().get(cid, {}).get("continuous"))
    time.sleep(3)
    rows = admin.get("/api/recordings", params={"camera_id": cid}).json()
    assert rows and rows[0]["kind"] == "continuous" and rows[0]["status"] == "recording"
    # exporting cuts the open part so the newest seconds can be downloaded too
    now = time.time()
    e = admin.get(f"/api/cameras/{cid}/export", params={"start": now - 2.5, "end": now})
    assert e.status_code == 200, e.text
    cam = admin.get("/api/cameras").json()[0]
    cam["record_mode"] = "off"
    admin.put(f"/api/cameras/{cid}", json=cam)
    assert _wait(lambda: not system.recorder.active().get(cid))
    assert admin.post("/api/cameras", json={"name": "X", "source": "0", "record_mode": "maybe"}).status_code == 400


def test_sighting_clip_on_route(admin, system, tmp_path):
    face = cv2.imread(str(sample("face.jpg")))
    admin.put("/api/settings", json={"clip_seconds": 5})
    pid = admin.post("/api/people", json={"full_name": "Asha"}).json()["id"]
    admin.post(f"/api/people/{pid}/samples", files=[("files", ("a.jpg", _jpg(face), "image/jpeg"))])
    vid = tmp_path / "hall.avi"
    _scene_video(vid, face)
    admin.put("/api/geo", json={"lat": -6.77, "lng": 39.24})
    admin.post("/api/cameras", json={"name": "Hall door", "source": str(vid), "map_x": 30, "map_y": 40})
    rows = _wait(lambda: [r for r in admin.get(f"/api/people/{pid}/timeline").json() if r["clip_id"]], 40)
    assert rows, "a clip was saved with the sighting"
    s = rows[0]
    assert s["lat"] < -6.76 and s["lng"] > 39.23
    clip = admin.get(f"/api/sightings/{s['id']}/clip").json()
    assert clip["kind"] == "clip" and 2.5 <= clip["duration"] <= 7
    assert admin.get(f"/api/recordings/{clip['id']}/download").status_code == 200
    # clips are not listed with camera recordings
    assert admin.get("/api/recordings").json() == []
    assert admin.get("/api/recordings", params={"kind": "clip"}).json()
    # erasing the person erases their clips
    admin.delete(f"/api/people/{pid}")
    assert admin.get(f"/api/recordings/{clip['id']}").status_code == 404


def test_recording_purge(admin, system, tmp_path):
    rec = system.recorder
    p = rec.folder / "9/old.mp4"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"x" * 100)
    old = time.time() - 30 * 86400
    rid = system.db.execute(
        "INSERT INTO recordings(camera_id, camera_name, kind, path, start_ts, end_ts, fps, frames, size_bytes, status) "
        "VALUES (NULL, 'Old', 'manual', '9/old.mp4', ?, ?, 8, 10, 100, 'done')", (old, old + 10))
    keep = system.db.execute(
        "INSERT INTO recordings(camera_id, camera_name, kind, path, start_ts, end_ts, fps, frames, size_bytes, status, keep) "
        "VALUES (NULL, 'Kept', 'manual', '9/kept.mp4', ?, ?, 8, 10, 100, 'done', 1)", (old, old + 10))
    assert rec.purge() >= 1
    assert not p.exists()
    assert system.db.one("SELECT id FROM recordings WHERE id = ?", (rid,)) is None
    assert system.db.one("SELECT id FROM recordings WHERE id = ?", (keep,)) is not None
