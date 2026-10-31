"""CAMS 1.6: power cuts and health, bags left behind, visitors, phones (guard view), number plates."""

import time

import cv2
import numpy as np
import pytest

from cams.activity import UnattendedCheck, parse_analytics
from cams.health import Health
from cams.plates import models_present, opencv_ok, pretty, similar


# ------------------------------------------------------------------ power cuts and health
def test_power_cut_is_reported_after_restart(admin, system):
    system.db.set_settings({"heartbeat": time.time() - 2 * 3600, "clean_stop": "0"})
    gap = Health(system).on_start()
    assert gap and 7000 < gap["seconds"] < 7400
    a = [x for x in admin.get("/api/alerts").json() if x["kind"] == "downtime"]
    assert a and "CAMS was off for 2 h" in a[0]["message"]
    # closed properly: listed on the health page, but no alert
    system.db.set_settings({"heartbeat": time.time() - 3600, "clean_stop": "1"})
    assert Health(system).on_start() is None
    r = admin.get("/api/health").json()
    assert [g["reason"] for g in r["downtime"]] == ["closed", "unexpected"]
    assert "cameras" in r and r["disk"]["total"] > 0 and r["ai"]["faces"]
    assert admin.put("/api/health/autostart", json={"on": True}).status_code == 400    # Windows only


def test_battery_alerts(system):
    hl = Health(system)
    hl.check_battery({"percent": 80, "plugged": True, "seconds_left": None})
    hl.check_battery({"percent": 79, "plugged": False, "seconds_left": 5400})
    hl.check_battery({"percent": 60, "plugged": False, "seconds_left": 3600})     # no second alert
    hl.check_battery({"percent": 12, "plugged": False, "seconds_left": 600})
    hl.check_battery({"percent": 13, "plugged": True, "seconds_left": None})
    msgs = [r["message"] for r in system.db.query("SELECT message FROM alerts WHERE kind = 'power' ORDER BY id")]
    assert len(msgs) == 3
    assert "running on battery (79%, about 1 h 30 min left)" in msgs[0]
    assert "almost empty" in msgs[1] and "Power is back" in msgs[2]


# ------------------------------------------------------------------ bags left behind
def test_bag_left_alone_raises_one_alert():
    u = UnattendedCheck()
    bag = (400, 300, 40, 50, 0.7, 24)                     # a backpack on the floor
    owner = (380, 150, 60, 200, 0.9)
    out = []
    for i in range(0, 400, 5):
        t = float(i)
        people = [owner] if t < 60 else []                # the owner walks away after one minute
        out += [(t, b["kind"]) for b in u.update([bag], people, t, minutes=3)]
    assert len(out) == 1 and out[0][1] == "backpack" and 235 <= out[0][0] <= 245


def test_bag_with_people_around_or_taken_is_fine():
    u = UnattendedCheck()
    bag = (400, 300, 40, 50, 0.7, 26)
    near = (420, 200, 50, 160, 0.9)
    assert not any(u.update([bag], [near], float(t), 1) for t in range(0, 300, 5))
    u = UnattendedCheck()
    hits = []
    for t in range(0, 300, 5):
        hits += u.update([bag] if t < 40 else [], [], float(t), 1)     # picked up after 40 s
    assert not hits


def test_bag_rule_off_by_default():
    assert parse_analytics(None)["unattended_minutes"] == 0


# ------------------------------------------------------------------ visitors
def test_visitor_check_in_rules_and_check_out(admin, system):
    adm = admin.post("/api/buildings", json={"name": "Administration", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}).json()["id"]
    lab = admin.post("/api/buildings", json={"name": "Science lab", "polygon": [[20, 0], [30, 0], [30, 10], [20, 10]]}).json()["id"]
    cam = admin.post("/api/cameras", json={"name": "Lab door", "source": "0", "kind": "usb", "building_id": lab}).json()["id"]
    system.refresh_areas()
    assert admin.post("/api/visitors", json={"full_name": ""}).status_code == 400
    v = admin.post("/api/visitors", json={"full_name": "Juma Ally", "phone": "0712 000 000", "host": "Mr Mushi",
                                          "purpose": "Meeting", "hours": 1, "allowed_areas": [adm]}).json()
    pid = v["person_id"]
    assert v["inside"] and not v["overstaying"] and v["faces"] == 0
    p = admin.get(f"/api/people/{pid}").json()
    assert p["category"] == "visitor" and p["consent_given"]
    person = system.names[pid]
    assert "outside the places they may visit" in system.access_problem(cam, person)
    assert [x["full_name"] for x in admin.get("/api/visitors?inside=true").json()] == ["Juma Ally"]
    # stays too long: one alert
    assert system.visitors.check_overstays(time.time() + 2 * 3600) == 1
    assert system.visitors.check_overstays(time.time() + 3 * 3600) == 0
    al = [a for a in admin.get("/api/alerts").json() if a["kind"] == "visitor_overstay"]
    assert al and "Juma Ally (visiting Mr Mushi) should have left" in al[0]["message"]
    # a face print, then check out: the face is forgotten, the visit is kept in the log
    system.db.add_face_sample(pid, np.ones(128, np.float32), "front", None, 0.9)
    system.reload_gallery()
    assert pid in set(system.gallery.ids.tolist())
    out = admin.post(f"/api/visitors/{v['id']}/checkout").json()
    assert not out["inside"] and out["checked_out_at"]
    assert pid not in set(system.gallery.ids.tolist())
    assert system.db.one("SELECT COUNT(*) AS n FROM face_samples WHERE person_id = ?", (pid,))["n"] == 0
    assert system.access_problem(cam, person) is None
    assert admin.get("/api/visitors?days=1").json()[0]["full_name"] == "Juma Ally"
    # the log is deleted after the keep time
    admin.post("/api/data/delete", json={"kinds": ["visitors"]})
    assert admin.get("/api/visitors?days=1").json() == []
    assert system.db.one("SELECT COUNT(*) AS n FROM people WHERE id = ?", (pid,))["n"] == 0


# ------------------------------------------------------------------ phones (guard view)
def test_guard_page_and_network_info(admin, client):
    assert "CAMS Guard" in client.get("/guard").text
    assert client.get("/static/js/guard.js").status_code == 200
    n = admin.get("/api/network").json()
    assert n["on"] is False and n["listening"] is False
    assert admin.put("/api/settings", json={"lan_access": "1"}).status_code == 200
    n = admin.get("/api/network").json()
    assert n["on"] and n["restart_needed"]
    for a in n["addresses"]:
        assert a["url"].endswith("/guard") and a["qr"].startswith("<svg")


def test_password_guessing_is_stopped(client, admin):
    codes = [client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code for _ in range(9)]
    assert codes[:8] == [401] * 8 and codes[8] == 429


# ------------------------------------------------------------------ number plates
def test_plate_text_helpers():
    assert pretty("T123ABC") == "T 123 ABC" and pretty("MC482DKM") == "MC 482 DKM"
    assert similar("T123ABC", "T123A8C") and similar("T1O3ABC", "T103ABC")
    assert not similar("T123ABC", "T456XYZ")


def _car_with_plate(text="T 482 DKM", seed=0):
    rng = np.random.default_rng(seed)
    img = np.clip(rng.normal(120, 30, (720, 1280, 3)), 0, 255).astype(np.uint8)
    cv2.rectangle(img, (500, 360), (860, 600), (40, 40, 160), -1)
    cv2.rectangle(img, (520, 300), (840, 380), (30, 30, 120), -1)
    plate = np.full((44, 200, 3), (10, 210, 245), np.uint8)
    cv2.rectangle(plate, (1, 1), (198, 42), (20, 20, 20), 2)
    cv2.putText(plate, text, (8, 32), cv2.FONT_HERSHEY_DUPLEX, 1.05, (15, 15, 15), 2, cv2.LINE_AA)
    img[520:564, 580:780] = plate
    return img


@pytest.fixture()
def plates_ready(system):
    if not (opencv_ok() and models_present(system.paths.models)):
        pytest.skip("number plate models not downloaded or OpenCV < 5")
    return system.plates


def test_plates_read_logged_and_alerted(admin, system, plates_ready):
    cam = admin.post("/api/cameras", json={"name": "Main gate", "source": "0", "kind": "usb"}).json()["id"]
    assert admin.put(f"/api/cameras/{cam}/analytics", json={"plates": True}).status_code == 200
    car = _car_with_plate()
    got = plates_ready.observe(cam, "Main gate", car, 1000.0, {"plates": True})
    assert [g["plate"] for g in got] == ["T482DKM"]
    plates_ready.observe(cam, "Main gate", car, 1003.0, {"plates": True})          # same visit
    log = admin.get("/api/vehicles?days=100000").json()
    assert len(log["rows"]) == 1 and log["rows"][0]["reads"] == 2 and log["rows"][0]["shown"] == "T 482 DKM"
    assert [c["name"] for c in log["cameras"]] == ["Main gate"]
    assert admin.get(f"/api/snapshots/{log['rows'][0]['image_path']}").status_code == 200
    # flag it: the next visit raises an alert
    assert admin.post("/api/plates", json={"plate": "t 482 dkm", "kind": "flagged", "owner": "Unknown", "note": "Seen at night"}).json()["shown"] == "T 482 DKM"
    plates_ready.observe(cam, "Main gate", car, 2000.0, {"plates": True})
    al = [a for a in admin.get("/api/alerts").json() if a["kind"] == "plate_flagged"]
    assert al and "Flagged vehicle T 482 DKM at Main gate" in al[0]["message"]
    # unknown vehicles alert only where asked
    other = _car_with_plate("T 915 BCX", seed=1)
    plates_ready.observe(cam, "Main gate", other, 3000.0, {"plates": True})
    assert not [a for a in admin.get("/api/alerts").json() if a["kind"] == "plate_unknown"]
    plates_ready.observe(cam, "Main gate", other, 4000.0, {"plates": True, "plates_alert_unknown": True})
    assert [a for a in admin.get("/api/alerts").json() if a["kind"] == "plate_unknown"]
    # nothing read in a picture without plates
    assert plates_ready.observe(cam, "Main gate", np.full((720, 1280, 3), 90, np.uint8), 5000.0, {"plates": True}) == []
    assert admin.get("/api/health").json()["ai"]["plates"] is True
