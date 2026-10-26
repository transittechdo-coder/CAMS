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
    assert {a["detected_angle"] for a in r["added"]} <= {"front", "left", "right", "up", "down"}
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
