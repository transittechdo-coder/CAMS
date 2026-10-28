"""Activity AI, routines, notes, daily report and Ask CAMS."""

import json
import time
from datetime import date, datetime
from types import SimpleNamespace

import cv2
import numpy as np

from conftest import sample
from cams.behaviour import FEATURE_NAMES, BehaviourEngine, TaughtModel, builtin_activity, guess_purpose, rule_activity


def vec(**kw):
    base = {k: 0.0 for k in FEATURE_NAMES}
    base.update(knee_l=0.95, knee_r=0.95, hip_l=0.95, hip_r=0.95, elbow_l=0.9, elbow_r=0.9, hand_mouth=0.6,
                head_down=0.3, legs_seen=0.9, pose_ok=1.0, aspect=0.4)
    base.update(kw)
    return np.array([base[k] for k in FEATURE_NAMES], np.float32)


def test_builtin_knowledge():
    assert builtin_activity(vec())[0] == "standing"
    assert builtin_activity(vec(speed=0.25, moving=1))[0] == "walking"            # 1 body height / s
    assert builtin_activity(vec(speed=0.7, moving=1))[0] == "running"
    assert builtin_activity(vec(tilt=0.9, aspect=1.8))[0] == "lying"
    assert builtin_activity(vec(tilt=0.9, aspect=1.8, near_bed=1))[0] == "sleeping"
    assert builtin_activity(vec(hip_l=0.5, hip_r=0.5, knee_l=0.5, knee_r=0.5))[0] == "sitting"
    assert builtin_activity(vec(hip_l=0.5, hip_r=0.5, near_drink=1, hand_drink=1))[0] == "eating"
    assert builtin_activity(vec(hip_l=0.5, hip_r=0.5, hand_mouth=0.08, near_table=1, place_dining=1))[0] == "eating"
    assert builtin_activity(vec(near_phone=1, hand_phone=1))[0] == "phone"
    assert builtin_activity(vec(near_book=1))[0] == "reading"
    assert builtin_activity(vec(near_ball=1, speed=0.3, moving=1))[0] == "sport"
    assert builtin_activity(vec(hip_l=0.5, hip_r=0.5, hand_up=1, place_classroom=1))[0] == "hand_up"


def test_taught_activities_win_over_builtin():
    m = TaughtModel()
    sweeping = [{"features": json.dumps(vec(elbow_l=0.4, elbow_r=0.4, head_down=0.9, speed=0.05).tolist()), "label": "Sweeping"} for _ in range(4)]
    m.load(sweeping)
    assert m.predict(vec(elbow_l=0.42, elbow_r=0.38, head_down=0.88, speed=0.05))[0] == "Sweeping"
    assert m.predict(vec(speed=0.9, moving=1, tilt=0.8)) is None      # nothing taught looks like this


def test_place_time_rules():
    rules = [{"activity": "Morning assembly", "start": "00:00", "end": "23:59", "area_ids": [7], "days": [], "body": "standing", "enabled": 1}]
    assert rule_activity(rules, {7}, set(), "standing") == "Morning assembly"
    assert rule_activity(rules, {7}, set(), "walking") is None       # body must match
    assert rule_activity(rules, {8}, set(), "standing") is None      # other place
    assert guess_purpose("Dining Hall") == "dining" and guess_purpose("DH") == "dining" and guess_purpose("Form 5 class") == "classroom"


def _jpg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_camera_pipeline_writes_timeline(admin, system):
    face = cv2.imread(str(sample("face.jpg")))
    player = cv2.imread(str(sample("player.jpg")))
    pid = admin.post("/api/people", json={"full_name": "Godwill Madunda"}).json()["id"]
    admin.post(f"/api/people/{pid}/samples", files=[("files", ("a.jpg", _jpg(face), "image/jpeg"))])
    system.reload_gallery()
    b = admin.post("/api/buildings", json={"name": "Sports ground", "kind": "field", "polygon": [[0, 0], [50, 0], [50, 40], [0, 40]], "purpose": "sports"}).json()
    cid = admin.post("/api/cameras", json={"name": "Pitch cam", "source": "0", "kind": "usb", "building_id": b["id"]}).json()["id"]
    system.refresh_areas()
    # the player with the enrolled face on his head, big enough to recognise
    frame = cv2.resize(player, None, fx=2.2, fy=2.2)
    fx, fy, fw, fh = system.analyse_image(face)[0].box
    crop = face[max(0, fy - int(0.3 * fh)):fy + int(1.2 * fh), max(0, fx - int(0.2 * fw)):fx + int(1.2 * fw)]
    head = cv2.resize(crop, (int(crop.shape[1] * 150 / crop.shape[0]), 150))
    frame[95:245, 530 - head.shape[1] // 2:530 - head.shape[1] // 2 + head.shape[1]] = head
    worker = SimpleNamespace(id=cid, restricted=False, state=SimpleNamespace(name="Pitch cam", overlays=[], people=[], overlays_at=0))
    from cams.face_engine import FaceEngine
    from cams.activity import PersonDetector
    eng = FaceEngine(system.paths.models)
    eng.person_detector = PersonDetector(system.paths.models)
    t0 = time.time()
    for i in range(4):
        overlays = system.process_frame(eng, worker, frame, t0 + i * 2.1)
    assert any(o["person_id"] == pid for o in overlays), "face not recognised in the test frame"
    rows = system.db.query("SELECT * FROM activity_log WHERE person_id = ?", (pid,))
    assert rows, "no timeline entry written"
    assert rows[0]["area_name"] == "Sports ground" and rows[0]["activity"] == "sport"
    assert rows[0]["image_path"] and admin.get(f"/api/snapshots/{rows[0]['image_path']}").status_code == 200

    day = admin.get(f"/api/people/{pid}/day").json()
    assert day["entries"][0]["label"] == "Playing sport"
    assert "Godwill" in day["summary"]

    # the admin corrects it -> the example becomes teaching data
    r = admin.put(f"/api/activity/entries/{rows[0]['id']}", json={"label": "Football training"})
    assert r.status_code == 200
    ex = admin.get("/api/activity/examples", params={"label": "Football training"}).json()
    assert len(ex) == 1
    assert any(t["key"] == "Football training" for t in admin.get("/api/activity/types").json())
    # erase the person: pictures go too
    admin.delete(f"/api/people/{pid}")
    assert system.db.query("SELECT * FROM activity_examples WHERE person_id = ?", (pid,)) == []


def _seen(system, pid, cam, name, hhmm_from, hhmm_to):
    today = date.today().isoformat()
    a = datetime.strptime(f"{today} {hhmm_from}", "%Y-%m-%d %H:%M").timestamp()
    b = datetime.strptime(f"{today} {hhmm_to}", "%Y-%m-%d %H:%M").timestamp()
    system.db.execute("INSERT INTO sightings(person_id, camera_id, camera_name, first_seen, last_seen, confidence) VALUES (?,?,?,?,?,?)",
                      (pid, cam, name, a, b, 0.8))


def test_routines_notes_report_and_ask(admin, system):
    poly = lambda x: [[x, 0], [x + 10, 0], [x + 10, 10], [x, 10]]
    dh = admin.post("/api/buildings", json={"name": "Dining Hall", "polygon": poly(0)}).json()["id"]
    lib = admin.post("/api/buildings", json={"name": "Library", "polygon": poly(20), "purpose": "library"}).json()["id"]
    c_dh = admin.post("/api/cameras", json={"name": "DH cam", "source": "0", "kind": "usb", "building_id": dh}).json()["id"]
    c_lib = admin.post("/api/cameras", json={"name": "Library cam", "source": "1", "kind": "usb", "building_id": lib}).json()["id"]
    system.refresh_areas()
    ids = {}
    for n in ("Asha Juma", "Baraka Moshi", "Cleo Mrema", "Dan Absent"):
        ids[n.split()[0]] = admin.post("/api/people", json={"full_name": n, "category": "student", "group_name": "Form 5"}).json()["id"]
    _seen(system, ids["Asha"], c_dh, "DH cam", "13:02", "13:35")          # on time
    _seen(system, ids["Baraka"], c_lib, "Library cam", "13:05", "13:40")  # elsewhere
    _seen(system, ids["Cleo"], c_dh, "DH cam", "13:25", "13:44")          # late
    system.db.execute("INSERT INTO activity_log(person_id, camera_id, camera_name, area_id, area_name, activity, start_ts, end_ts) VALUES (?,?,?,?,?,?,?,?)",
                      (ids["Baraka"], c_lib, "Library cam", lib, "Library", "reading",
                       datetime.strptime(f"{date.today()} 13:06", "%Y-%m-%d %H:%M").timestamp(),
                       datetime.strptime(f"{date.today()} 13:38", "%Y-%m-%d %H:%M").timestamp()))
    # the DH has no purpose set: CAMS guesses "dining" from its name
    rid = admin.post("/api/routines", json={"name": "Lunch", "start": "13:00", "end": "13:45", "days": list(range(7)),
                                            "purpose": "dining", "who_groups": ["Form 5"]}).json()["id"]
    res = admin.post(f"/api/routines/{rid}/check").json()
    assert res["counts"] == {"attended": 1, "missed": 1, "late": 1}

    notes = admin.get(f"/api/people/{ids['Baraka']}/day").json()["notes"]
    text = notes[0]["text"]
    assert "Baraka did not go to the Dining Hall during Lunch" in text and "Library" in text and "reading" in text
    late = admin.get(f"/api/people/{ids['Cleo']}/day").json()["notes"][0]["text"]
    assert "came late to Lunch" in late and "1:25 PM" in late

    rep = admin.get("/api/report/daily").json()
    assert rep["seen"] == 3 and rep["missed"] == 1 and rep["late"] == 1
    assert "Baraka" in admin.get("/api/report/daily.csv").text

    def ask(q):
        return admin.post("/api/ask", json={"question": q}).json()

    a = ask("Who missed lunch today?")
    assert a["intent"] == "missed" and [i["name"] for i in a["items"]] == ["Baraka Moshi"]
    assert [i["name"] for i in ask("who was late for lunch")["items"]] == ["Cleo Mrema"]
    assert "Library" in ask("Where was Baraka at 1:10 PM?")["answer"]
    assert "reading" in ask("What was Baraka doing at 1:15 pm?")["answer"]
    assert {i["name"] for i in ask("who was in the dining hall today")["items"]} == {"Asha Juma", "Cleo Mrema"}
    assert [i["name"] for i in ask("who was reading today?")["items"]] == ["Baraka Moshi"]
    assert [i["name"] for i in ask("Who was not seen today")["items"]] == ["Dan Absent"]
    assert ask("blah blah")["intent"] == "help"

    # summaries + habits
    assert admin.post("/api/report/daily/summaries").json()["people"] == 3
    day = admin.get(f"/api/people/{ids['Asha']}/day").json()
    assert any(n["kind"] == "summary" and "first seen at 1:02 PM in the Dining Hall" in n["text"] for n in day["notes"])
    assert day["habits"]["days_seen"] == 1
