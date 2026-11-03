"""Offline licence checks, using a real file signed by the CAMS licence server."""
import base64
import json
from datetime import datetime, timedelta, timezone

from cams import licence as lic

GENUINE = {
    "alg": "Ed25519",
    "data": "eyJ2IjoxLCJsaWNlbmNlX2lkIjoiODk4ZDY0MDEtYzczYy00Njk0LTg4NzEtOWQ5MWNkNGRlYTA0Iiwia2V5X2hpbnQiOiJFUFVQIiwiY3VzdG9tZXIiOm51bGwsInN0YXRlIjoiYWN0aXZlIiwicGxhbiI6InBybyIsInBsYW5fbmFtZSI6IlBybyIsInBhaWRfcGxhbiI6InBybyIsIm1heF9jYW1lcmFzIjo2LCJtYXhfcGhvbmVzIjoxLCJmZWF0dXJlcyI6WyJsaXZlX3ZpZXciLCJyZWNvcmRpbmciLCJjbGlwX2Rvd25sb2FkIiwiZW1lcmdlbmN5X2FsZXJ0cyIsIm1vdGlvbl9hbGVydHMiLCJjbGlwX2V4cG9ydCIsImRhaWx5X3JlcG9ydCIsImd1YXJkX2FwcCJdLCJhbHdheXNfb24iOlsibGl2ZV92aWV3IiwicmVjb3JkaW5nIiwiZW1lcmdlbmN5X2FsZXJ0cyJdLCJkZXZpY2UiOiJhNmQ3NGYzMWMzZGRlZDdjOTk4ZDQyNDU5YzcwMGRkNTA5YmU0MjFjMWY5ODQ1Y2NiNTAzNDE2MWQ5ZjcyZDlkIiwidHJpYWxfZW5kc19hdCI6IjIwMjYtMTEtMTdUMDg6NDg6NTMuNDk4WiIsInBhaWRfdW50aWwiOiIyMDI3LTExLTAzVDA4OjQ5OjI0Ljg0MFoiLCJncmFjZV91bnRpbCI6IjIwMjctMTEtMTNUMDg6NDk6MjQuODQwWiIsImlzc3VlZF9hdCI6IjIwMjYtMTEtMDNUMDg6NDk6MjUuNTAwWiIsInZhbGlkX3VudGlsIjoiMjAyNi0xMS0xN1QwODo0OToyNS41MDBaIiwicmVuZXdfYWZ0ZXIiOiIyMDI2LTExLTEwVDA4OjQ5OjI1LjUwMFoifQ==",
    "sig": "YQ5ZVxtcVZF6dx/ddBtNNdDJT5qdfYmBdUpizbrIMjH2Syg5g5JAOjVX1rVy879Th/+0MxIszeYcwgFwWZMzBQ==",
}
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


def check(f, **kw):
    return lic.check_licence(f, now=kw.pop("now", NOW), check_clock=False, **kw)


def test_genuine_file_unlocks_its_plan():
    s = check(GENUINE)
    assert s.state == "active" and s.plan == "pro" and s.max_cameras == 6
    assert s.has("motion_alerts") and not s.has("face_recognition")


def test_right_and_wrong_computer():
    assert check(GENUINE, fingerprint="TEST-PC-001").state == "active"
    s = check(GENUINE, fingerprint="OTHER-PC")
    assert s.state == "invalid" and s.has("recording")


def test_edited_file_is_rejected_but_recording_stays_on():
    data = json.loads(base64.b64decode(GENUINE["data"]))
    data["max_cameras"] = 99
    edited = dict(GENUINE, data=base64.b64encode(json.dumps(data).encode()).decode())
    s = check(edited)
    assert s.state == "invalid" and s.max_cameras == lic.FREE_MAX_CAMERAS
    assert s.has("recording") and s.has("live_view") and s.has("emergency_alerts")


def test_too_long_offline_locks_paid_features_only():
    s = check(GENUINE, now=NOW + timedelta(days=20))
    assert s.state == "limited" and s.needs_online_check
    assert s.has("recording") and not s.has("motion_alerts")
    assert s.banner


# ---------------------------------------------------------------- inside the CAMS app
import pytest  # noqa: E402


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """CAMS with plan limits switched on (no AI models needed)."""
    monkeypatch.setenv("CAMS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CAMS_LICENCE_ENFORCE", "1")
    monkeypatch.setattr(lic, "_now", lambda: NOW)
    monkeypatch.setattr(lic, "_fp_cache", "TEST-PC-001")
    from fastapi.testclient import TestClient

    from cams.api import create_app
    from cams.config import get_paths
    from cams.system import CamsSystem

    s = CamsSystem(get_paths(), start_cameras=False)
    with TestClient(create_app(s)) as c:
        r = c.post("/api/setup", json={"site_name": "Test School", "username": "admin", "password": "secret123"})
        assert r.status_code == 200, r.text
        yield c
    s.stop()


def add_cam(c, name):
    return c.post("/api/cameras", json={"name": name, "source": "0"})


def test_free_plan_allows_two_cameras(app_client):
    st = app_client.get("/api/status").json()["licence"]
    assert st["state"] == "free" and st["max_cameras"] == 2 and not st["welcome_done"]
    assert add_cam(app_client, "Gate").status_code == 200
    assert add_cam(app_client, "Hall").status_code == 200
    r = add_cam(app_client, "Library")
    assert r.status_code == 402 and "2 cameras" in r.json()["error"]


def test_free_plan_cannot_enrol_faces(app_client):
    pid = app_client.post("/api/people", json={"full_name": "Asha Juma", "category": "student"}).json()["id"]
    r = app_client.post(f"/api/people/{pid}/samples", files={"files": ("a.jpg", b"x", "image/jpeg")})
    assert r.status_code == 402 and "Face recognition" in r.json()["error"]


def test_paid_licence_lifts_the_limits(app_client, tmp_path):
    (tmp_path / "data" / lic.LICENCE_FILE).write_text(json.dumps(GENUINE))
    (tmp_path / "data" / lic.KEY_FILE).write_text("CAMS-R4FM-JPGD-YUL6-EPUP")
    st = app_client.get("/api/licence").json()
    assert st["state"] == "active" and st["plan_name"] == "Pro" and st["key_hint"].endswith("EPUP")
    for i in range(6):
        assert add_cam(app_client, f"Cam {i}").status_code == 200
    assert add_cam(app_client, "Cam 7").status_code == 402


def test_server_errors_reach_the_user(app_client, monkeypatch):
    def boom(*a, **k):
        raise lic.LicenceError("key_not_found", "Key not found. Check the key and try again.", 404)
    monkeypatch.setattr(lic, "_call", boom)
    r = app_client.post("/api/licence/activate", json={"licence_key": "CAMS-AAAA-BBBB-CCCC-DDDD"})
    assert r.status_code == 404 and "Key not found" in r.json()["error"]


def test_welcome_can_be_skipped(app_client):
    assert app_client.post("/api/licence/welcome-done").status_code == 200
    assert app_client.get("/api/licence").json()["welcome_done"] is True
