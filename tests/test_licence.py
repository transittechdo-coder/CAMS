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
