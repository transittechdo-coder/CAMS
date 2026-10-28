import time

import cv2
import numpy as np

from conftest import sample


def test_setup_and_login_flow(client):
    s = client.get("/api/status").json()
    assert s["needs_setup"] is True and s["user"] is None
    assert client.get("/api/people").status_code == 401
    bad = client.post("/api/setup", json={"site_name": "X", "username": "admin", "password": "short"})
    assert bad.status_code == 400
    ok = client.post("/api/setup", json={"site_name": "Mikocheni", "username": "admin", "password": "secret123"})
    assert ok.status_code == 200
    assert client.post("/api/setup", json={"site_name": "X", "username": "bob", "password": "secret123"}).status_code == 409
    assert client.get("/api/status").json()["user"]["role"] == "admin"
    client.post("/api/logout")
    assert client.post("/api/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"username": "ADMIN", "password": "secret123"}).status_code == 200


def test_roles(admin):
    admin.post("/api/users", json={"username": "guard", "password": "guard1234", "role": "viewer"})
    admin.post("/api/logout")
    admin.post("/api/login", json={"username": "guard", "password": "guard1234"})
    assert admin.get("/api/people").status_code == 200
    assert admin.post("/api/people", json={"full_name": "X"}).status_code == 403
    assert admin.get("/api/audit").status_code == 403


def test_people_crud_and_csv_import(admin):
    pid = admin.post("/api/people", json={"full_name": "Asha Juma", "person_code": "S001", "group_name": "Form 5 PCM"}).json()["id"]
    assert admin.get(f"/api/people/{pid}").json()["full_name"] == "Asha Juma"
    csv_data = "full_name,person_code,category,group_name\nBaraka Mushi,S002,student,Form 6\nNeema,T01,staff,Science\n"
    r = admin.post("/api/people/import", files={"file": ("p.csv", csv_data, "text/csv")})
    assert r.json()["added"] == 2
    assert len(admin.get("/api/people", params={"q": "S00"}).json()) == 2
    assert admin.get("/api/people/groups").json() == ["Form 5 PCM", "Form 6", "Science"]
    assert admin.delete(f"/api/people/{pid}").status_code == 200
    assert admin.get(f"/api/people/{pid}").status_code == 404


def _jpg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_multi_angle_enrol_and_photo_search(admin, system):
    face = cv2.imread(str(sample("face.jpg")))
    pid = admin.post("/api/people", json={"full_name": "Test Face", "consent_given": True}).json()["id"]
    files = [("files", ("a.jpg", _jpg(face), "image/jpeg")),
             ("files", ("b.jpg", _jpg(cv2.flip(face, 1)), "image/jpeg")),
             ("files", ("blank.jpg", _jpg(np.full((300, 300, 3), 128, np.uint8)), "image/jpeg"))]
    r = admin.post(f"/api/people/{pid}/samples", files=files).json()
    assert len(r["added"]) == 2 and len(r["errors"]) == 1
    from cams.face_engine import ANGLES
    assert {a["detected_angle"] for a in r["added"]} <= set(ANGLES)
    assert len(system.gallery) == 2
    assert admin.get(f"/api/people/{pid}/photo").status_code == 200

    # search with a smaller, slightly rotated copy
    h, w = face.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 8, 0.8)
    probe = cv2.warpAffine(face, m, (w, h), borderMode=cv2.BORDER_REPLICATE)
    res = admin.post("/api/search/photo", files={"file": ("p.jpg", _jpg(probe), "image/jpeg")}).json()
    assert res["results"][0]["id"] == pid and res["results"][0]["is_match"]

    chk = admin.post("/api/faces/check", files={"file": ("p.jpg", _jpg(face), "image/jpeg")}).json()
    assert len(chk["faces"]) == 1


def test_camera_recognition_sightings_and_last_seen(admin, system, tmp_path):
    face = cv2.imread(str(sample("face.jpg")))
    pid = admin.post("/api/people", json={"full_name": "Walker", "alert_on_sight": True}).json()["id"]
    admin.post(f"/api/people/{pid}/samples", files=[("files", ("a.jpg", _jpg(face), "image/jpeg"))])

    # a "camera" that is a short video of the enrolled face on a background
    vid = tmp_path / "gate.avi"
    vw = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"MJPG"), 10, (960, 540))
    for i in range(40):
        bg = np.full((540, 960, 3), 60, np.uint8)
        x = 100 + i * 5
        bg[10:522, x:x + 512] = face
        vw.write(bg)
    vw.release()

    b = admin.post("/api/buildings", json={"name": "Library", "polygon": [[0, 0], [20, 0], [20, 10], [0, 10]], "height_m": 8}).json()
    cid = admin.post("/api/cameras", json={"name": "Main Gate", "source": str(vid), "map_x": 10, "map_y": 5,
                                            "building_id": b["id"]}).json()["id"]
    deadline = time.time() + 30
    rows = []
    while time.time() < deadline:
        rows = admin.get("/api/sightings", params={"person_id": pid}).json()
        if rows:
            break
        time.sleep(0.5)
    assert rows, "the enrolled face was never recognised on the camera"
    assert rows[0]["camera_name"] == "Main Gate"
    # merged into one sighting rather than one per frame
    time.sleep(2)
    assert len(admin.get("/api/sightings", params={"person_id": pid}).json()) == 1

    found = admin.get("/api/search/last-seen", params={"q": "walk"}).json()
    assert found[0]["last_seen"]["camera_name"] == "Main Gate"
    assert found[0]["last_seen"]["building_name"] == "Library"
    assert admin.get(f"/api/people/{pid}/timeline").json()

    alerts = admin.get("/api/alerts").json()
    assert any(a["kind"] == "watchlist" and a["person_id"] == pid for a in alerts)

    assert admin.get(f"/api/cameras/{cid}/snapshot.jpg").status_code == 200
    snap = rows[0]["snapshot_path"]
    assert snap and admin.get(f"/api/snapshots/{snap}").status_code == 200
    assert admin.get("/api/snapshots/../cams.db").status_code == 404

    m = admin.get("/api/map").json()
    assert m["cameras"][0]["live"]["status"] in ("online", "starting")
    assert admin.get("/api/dashboard").json()["people_today"] == 1

    # erase the person: sightings and files go too
    admin.delete(f"/api/people/{pid}")
    assert admin.get("/api/sightings", params={"person_id": pid}).json() == []


def test_settings_validation_and_backup(admin):
    assert admin.put("/api/settings", json={"match_threshold": "0.1"}).status_code == 400
    assert admin.put("/api/settings", json={"retention_days": "7", "blur_unknown": "1"}).status_code == 200
    assert admin.get("/api/settings").json()["retention_days"] == "7"
    r = admin.get("/api/backup")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert admin.get("/").status_code == 200


def test_source_helpers():
    from cams.cameras import detect_kind, mask_source

    assert detect_kind("0") == "usb"
    assert detect_kind("rtsp://a:b@1.2.3.4/x") == "rtsp"
    assert detect_kind("http://1.2.3.4:8080/video") == "http"
    assert mask_source("rtsp://admin:pass@10.0.0.5:554/s") == "rtsp://admin:****@10.0.0.5:554/s"


def _face_video(path, face, frames=40, size=(960, 540)):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, size)
    for i in range(frames):
        bg = np.full((size[1], size[0], 3), 60, np.uint8)
        x = 100 + (i % 20) * 5
        bg[10:522, x:x + 512] = face
        vw.write(bg)
    vw.release()


def _wait(fn, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        r = fn()
        if r:
            return r
        time.sleep(0.5)
    return None


def test_reference_photos_and_video_enrolment(admin, tmp_path):
    face = cv2.imread(str(sample("face.jpg")))
    pid = admin.post("/api/people", json={"full_name": "Round Head"}).json()["id"]
    back = np.full((400, 300, 3), 90, np.uint8)
    r = admin.post(f"/api/people/{pid}/samples", files=[("files", ("back.jpg", _jpg(back), "image/jpeg"))], data={"angle": "back"}).json()
    assert r["added"][0]["reference"] is True
    vid = tmp_path / "turn.avi"
    _face_video(vid, face, frames=20)
    v = admin.post(f"/api/people/{pid}/samples/video", files={"file": ("turn.avi", vid.read_bytes(), "video/x-msvideo")}).json()
    assert v["added"] and v["frames_checked"] > 0
    p = admin.get(f"/api/people/{pid}").json()
    assert len(p["references"]) == 1 and len(p["samples"]) >= 1
    rid = p["references"][0]["id"]
    assert admin.get(f"/api/references/{rid}/image").status_code == 200
    assert admin.delete(f"/api/references/{rid}").status_code == 200


def test_access_rules_alert(admin, system, tmp_path):
    face = cv2.imread(str(sample("face.jpg")))
    pid = admin.post("/api/people", json={"full_name": "Form One Kid", "category": "student", "group_name": "Form 1"}).json()["id"]
    admin.post(f"/api/people/{pid}/samples", files=[("files", ("a.jpg", _jpg(face), "image/jpeg"))])
    bad = admin.post("/api/buildings", json={"name": "Lab", "polygon": [[0, 0], [5, 0], [5, 5]], "closed_hours": "25:00-1"})
    assert bad.status_code == 400
    lab = admin.post("/api/buildings", json={"name": "Staff room", "polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                                             "access_mode": "allow", "access_categories": ["staff"]}).json()["id"]
    m = admin.get("/api/map").json()
    assert m["buildings"][0]["access_categories"] == ["staff"]
    vid = tmp_path / "staffroom.avi"
    _face_video(vid, face)
    admin.post("/api/cameras", json={"name": "Staff room door", "source": str(vid), "building_id": lab, "map_x": 5, "map_y": 5})
    hit = _wait(lambda: [a for a in admin.get("/api/alerts").json() if a["kind"] == "access_violation"])
    assert hit and "Form One Kid" in hit[0]["message"] and "Staff room" in hit[0]["message"]


def test_access_rule_logic(system):
    system.db.execute("INSERT INTO cameras(name, source, kind, building_id, created_at) VALUES ('c', '0', 'usb', NULL, 0)")
    cid = system.db.one("SELECT id FROM cameras")["id"]
    import json as _j
    system.db.execute(
        "INSERT INTO buildings(name, kind, polygon, access_mode, access_groups, closed_hours) VALUES (?,?,?,?,?,?)",
        ("Lab", "zone", _j.dumps([[0, 0], [10, 0], [10, 10], [0, 10]]), "deny", _j.dumps(["Form 1"]), "18:00-06:00"))
    system.db.execute("UPDATE cameras SET map_x = 5, map_y = 5 WHERE id = ?", (cid,))
    system.refresh_areas()
    from datetime import datetime
    noon, night = datetime(2026, 1, 5, 12, 0), datetime(2026, 1, 5, 22, 0)
    f1 = {"id": 1, "full_name": "A", "category": "student", "group_name": "Form 1"}
    f5 = {"id": 2, "full_name": "B", "category": "student", "group_name": "Form 5"}
    assert "not allowed" in system.access_problem(cid, f1, noon)
    assert system.access_problem(cid, f5, noon) is None
    assert "closed hours" in system.access_problem(cid, f5, night)


def test_activity_rules():
    from datetime import datetime

    from cams.activity import ActivityMonitor, in_hours

    assert in_hours("18:00-06:00", datetime(2026, 1, 1, 23, 0))
    assert in_hours("18:00-06:00", datetime(2026, 1, 1, 5, 59))
    assert not in_hours("18:00-06:00", datetime(2026, 1, 1, 12, 0))
    mon = ActivityMonitor()
    rng = np.random.default_rng(1)
    scene = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
    rules = {"tamper": True, "crowd_count": 3, "running": True, "loiter_minutes": 0.05}
    events = []
    t = 1000.0
    # someone runs across the view
    for i in range(12):
        x = 20 + i * 60
        events += mon.analyse(scene, t, [(x, 100, 40, 100, 0.9)], rules, "", "Gate")
        t += 0.25
    assert any(k == "running" for k, _ in events)
    # three people standing for 10+ seconds -> crowd, and loitering after 3 s
    events = []
    for i in range(50):
        events += mon.analyse(scene, t, [(50, 50, 40, 100, .9), (200, 50, 40, 100, .9), (400, 50, 40, 100, .9)], rules, "", "Gate")
        t += 0.5
    kinds = {k for k, _ in events}
    assert {"crowd", "loitering"} <= kinds
    # camera covered for 15+ seconds
    events = []
    black = np.zeros_like(scene)
    for i in range(40):
        events += mon.analyse(black, t, [], rules, "", "Gate")
        t += 0.5
    assert any(k == "tamper" for k, _ in events)


def test_person_detector_on_sample_video():
    from pathlib import Path

    from cams.activity import PersonDetector
    from cams.config import get_paths

    models = get_paths().models
    if not PersonDetector.available(models):
        import pytest
        pytest.skip("person model not downloaded")
    cap = cv2.VideoCapture(str(sample("video.avi")))
    for _ in range(3):
        ok, frame = cap.read()
    people = PersonDetector(models).detect(frame)
    assert len(people) >= 2


def test_old_database_is_upgraded(tmp_path):
    import sqlite3

    from cams.db import Database

    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript("CREATE TABLE buildings (id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'building', "
                    "polygon TEXT NOT NULL, height_m REAL NOT NULL DEFAULT 6, floors INTEGER NOT NULL DEFAULT 1, color TEXT NOT NULL DEFAULT '#5b8def');"
                    "INSERT INTO buildings(name, polygon) VALUES ('Old', '[[0,0],[1,0],[1,1]]');")
    c.close()
    db = Database(p)
    row = db.one("SELECT * FROM buildings")
    assert row["access_mode"] == "everyone" and row["floor_names"] == "[]"


def test_map_scene_roundtrip(admin):
    client = admin
    r = client.get("/api/map/scene")
    assert r.status_code == 200 and r.json()["objects"] == []
    doc = {"version": 1, "objects": [{"id": "o1", "type": "building", "pos": [10, 0, 10], "size": [20, 6.4, 10], "props": {"floors": 2}},
                                     {"id": "o2", "type": "roofHip", "pos": [10, 6.4, 10], "size": [21, 2.5, 11]}], "paint": None}
    assert client.put("/api/map/scene", json=doc).json()["objects"] == 2
    got = client.get("/api/map/scene").json()
    assert [o["type"] for o in got["objects"]] == ["building", "roofHip"]
    assert client.put("/api/map/scene", json={"objects": "nope"}).status_code == 400
    assert client.put("/api/map/scene", json={"objects": [], "paint": "javascript:x"}).status_code == 400


def test_screen_files_are_revalidated(client):
    # after an update the window must not keep showing the old screens
    r = client.get("/static/js/app.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_window_cache_cleared_once_per_version(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMS_DATA_DIR", str(tmp_path / "d"))
    from cams import __version__, main
    from cams.config import get_paths

    data = get_paths().data
    cache = data / "webview" / "EBWebView" / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "old.js").write_text("old")
    keep = data / "webview" / "EBWebView" / "Default" / "Preferences"
    keep.write_text("{}")
    main._clear_window_cache()
    assert not cache.exists() and keep.exists()
    assert (data / "window-version.txt").read_text() == __version__
