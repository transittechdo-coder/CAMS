"""Emergency detection: fire, heavy smoke, person down - and things that must NOT raise an alarm."""

import numpy as np
import cv2

from cams.activity import Track, parse_analytics
from cams.emergency import EmergencyMonitor

RULES = parse_analytics(None)
RNG = np.random.default_rng(7)


def scene(w=640, h=360):
    """A view with detail: walls, windows, floor tiles, a door."""
    img = np.full((h, w, 3), (150, 160, 165), np.uint8)
    for x in range(0, w, 40):
        cv2.line(img, (x, h // 2), (x, h), (110, 115, 120), 2)
    for y in range(h // 2, h, 30):
        cv2.line(img, (0, y), (w, y), (110, 115, 120), 2)
    for x in range(30, w, 120):
        cv2.rectangle(img, (x, 40), (x + 60, 120), (90, 70, 40), -1)
        cv2.rectangle(img, (x + 5, 45), (x + 55, 115), (200, 190, 170), 2)
    noise = RNG.integers(-12, 12, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def flame(img, cx, cy, size, t):
    """Draw a flickering flame: its outline changes every picture."""
    rng = np.random.default_rng(int(t * 1000))
    pts = []
    for i in range(14):
        a = np.pi * i / 13
        r = size * (0.6 + 0.6 * rng.random())
        pts.append((cx + r * np.cos(a) * 0.6, cy - r * np.sin(a) * (1.2 + rng.random())))
    pts = np.array(pts, np.int32)
    cv2.fillPoly(img, [pts], (0, 110, 255))                     # orange
    cv2.fillPoly(img, [((pts - [cx, cy]) * 0.55 + [cx, cy]).astype(np.int32)], (60, 220, 255))  # yellow core
    return img


def run(frames, people=None, tracks=None, rules=RULES, objects=None, tilt=None):
    em = EmergencyMonitor()
    out = []
    for ts, img in frames:
        ev = em.analyse(img, ts, tracks(ts) if tracks else None, people or [], objects or [], rules, "Store room",
                        tilt_of=tilt)
        out += [(ts, k) for k, _, _ in ev]
    return out


def test_fire_is_found():
    bg = scene()
    frames = [(i * 0.5, flame(bg.copy(), 320, 300, 40, i * 0.5)) for i in range(16)]
    hits = run(frames)
    assert any(k == "fire" for _, k in hits)
    assert min(t for t, k in hits if k == "fire") <= 4.5


def test_fire_on_black_and_white_night_camera():
    bg = cv2.cvtColor(cv2.cvtColor(scene(), cv2.COLOR_BGR2GRAY) // 3, cv2.COLOR_GRAY2BGR)
    frames = []
    for i in range(16):
        img = flame(bg.copy(), 320, 300, 40, i * 0.5)
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        g[g > 120] = 255                                          # infrared: flames glow white
        frames.append((i * 0.5, cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)))
    assert any(k == "fire" for _, k in run(frames))


def test_orange_things_are_not_fire():
    bg = scene()
    still = bg.copy()
    cv2.rectangle(still, (250, 200), (360, 300), (0, 110, 255), -1)   # an orange door or poster
    cv2.circle(still, (500, 80), 20, (255, 255, 255), -1)              # a lamp
    assert run([(i * 0.5, still) for i in range(30)]) == []
    moving = []                                                         # an orange car driving past
    for i in range(30):
        img = bg.copy()
        x = 20 * i
        cv2.rectangle(img, (x, 220), (x + 110, 290), (0, 110, 255), -1)
        moving.append((i * 0.5, img))
    assert not any(k == "fire" for _, k in run(moving))


def test_fire_rule_can_be_turned_off():
    bg = scene()
    frames = [(i * 0.5, flame(bg.copy(), 320, 300, 40, i * 0.5)) for i in range(16)]
    assert not run(frames, rules={**RULES, "fire": False})


def smoke_frames(bg, seconds=30, start=6):
    out = []
    for i in range(int(seconds * 2)):
        t = i * 0.5
        img = bg.copy()
        if t > start:
            a = min(0.92, (t - start) / 8)                          # the haze thickens over a few seconds
            veil = cv2.GaussianBlur(img, (0, 0), 6)
            grey = np.full_like(img, 175)
            mix = (veil * (1 - a) + grey * a).astype(np.uint8)
            img[:, :400] = mix[:, :400]                             # covers the left part of the view
        out.append((t, img))
    return out


def test_heavy_smoke_is_found():
    hits = run(smoke_frames(scene()))
    assert any(k == "smoke" for _, k in hits)


def test_lights_off_or_night_mode_is_not_smoke():
    bg = scene()
    frames = [(i * 0.5, bg) for i in range(12)]
    dark = (bg * 0.35).astype(np.uint8)
    ir = cv2.cvtColor(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    frames += [(6 + i * 0.5, dark) for i in range(30)] + [(21 + i * 0.5, ir) for i in range(30)]
    assert not any(k == "smoke" for _, k in run(frames))


# ------------------------------------------------------------------ person down
def tracks_for(boxes_at):
    tr = Track(1, boxes_at(0), 0, 0)

    def at(ts):
        b = boxes_at(ts)
        if b is None:
            return []
        cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
        tr.box, tr.last_seen = b, ts
        tr.history.append((ts, cx, cy, b[3]))
        return [tr]
    return at


STAND = (300, 100, 60, 170)
LIE = (240, 250, 180, 60)


def test_person_lying_still_raises_alarm():
    bg = scene()
    tr = tracks_for(lambda t: LIE)
    hits = run([(i * 0.5, bg) for i in range(60)], people=[LIE], tracks=tr)
    downs = [t for t, k in hits if k == "person_down"]
    assert downs and 19 <= downs[0] <= 22 and len(downs) == 1        # once, after 20 seconds


def test_fall_is_reported_sooner():
    bg = scene()
    tr = tracks_for(lambda t: STAND if t < 5 else LIE)
    hits = run([(i * 0.5, bg) for i in range(60)], tracks=tr)
    downs = [t for t, k in hits if k == "person_down"]
    assert downs and 16 <= downs[0] <= 19            # 12 seconds after the fall


def test_standing_sitting_or_lying_on_a_bed_is_fine():
    bg = scene()
    assert not run([(i * 0.5, bg) for i in range(80)], tracks=tracks_for(lambda t: STAND))
    bed = (230, 240, 200, 80, 0.8, 59)
    assert not run([(i * 0.5, bg) for i in range(80)], tracks=tracks_for(lambda t: LIE), objects=[bed])


def test_pose_overrides_shape():
    bg = scene()
    # wide box but the body pose is upright (arms out, or a person seen from above): no alarm
    assert not run([(i * 0.5, bg) for i in range(80)], tracks=tracks_for(lambda t: LIE), tilt=lambda t: 0.1)
    # tall box but the body is flat (lying towards the camera): alarm
    hits = run([(i * 0.5, bg) for i in range(80)], tracks=tracks_for(lambda t: STAND), tilt=lambda t: 0.9)
    assert any(k == "person_down" for _, k in hits)


def test_emergency_alert_reaches_the_app(admin, system):
    cam = admin.post("/api/cameras", json={"name": "Store room", "source": "0", "kind": "usb"}).json()["id"]
    listed = next(c for c in admin.get("/api/cameras").json() if c["id"] == cam)
    assert listed["analytics"]["fire"] is True and listed["analytics"]["person_down"] is True
    assert admin.put(f"/api/cameras/{cam}/analytics", json={"fire": True, "down_seconds": 2}).status_code == 400
    assert admin.put("/api/settings", json={"emergency_sensitivity": "high", "alarm_sound": "0"}).status_code == 200
    assert admin.put("/api/settings", json={"emergency_sensitivity": "max"}).status_code == 400

    class W:
        id = cam

        class state:
            name = "Store room"

    from cams.activity import ActivityMonitor
    mon = ActivityMonitor()
    bg = scene()
    for i in range(16):
        system._check_emergencies(W, flame(bg.copy(), 320, 300, 40, i * 0.5), 1000 + i * 0.5, mon, [], [], parse_analytics(None), [])
    a = admin.get("/api/alerts").json()
    fire = [x for x in a if x["kind"] == "fire"]
    assert len(fire) == 1 and "FIRE" in fire[0]["message"] and fire[0]["snapshot_path"]
    assert admin.get(f"/api/snapshots/{fire[0]['snapshot_path']}").status_code == 200
    assert admin.post("/api/alerts/test-emergency").status_code == 200
    assert admin.get("/api/alerts").json()[0]["kind"] == "emergency_test"
    em = admin.get("/api/alerts/emergencies").json()
    assert {x["kind"] for x in em} == {"fire", "emergency_test"}
    for x in em:
        admin.post(f"/api/alerts/{x['id']}/ack")
    assert admin.get("/api/alerts/emergencies").json() == []


# ------------------------------------------------------------------ the trained second opinion (1.8)
class FakeAI:
    """Stands in for the trained fire / smoke checker."""
    def __init__(self, fire=0.0, smoke=0.0):
        self.p = np.array([[1 - fire - smoke, fire, smoke]], np.float32)
        self.calls = 0

    def features(self, crops):
        self.calls += 1
        return np.ones((len(crops), 1280), np.float32)

    def probs(self, feats):
        return np.repeat(self.p, len(feats), axis=0)


def run_ai(frames, ai, rules=RULES, sens="normal"):
    from cams.emergency import EmergencyMonitor
    em = EmergencyMonitor()
    out = []
    for ts, img in frames:
        out += [(ts, k) for k, _, _ in em.analyse(img, ts, None, [], [], rules, "Store room", sens, ai=ai)]
    return out, em


def test_fire_needs_the_ai_to_agree():
    bg = scene()
    frames = [(i * 0.5, flame(bg.copy(), 320, 300, 40, i * 0.5)) for i in range(16)]
    hits, em = run_ai(frames, FakeAI(fire=0.02))            # the AI sees no fire: no alarm
    assert not any(k == "fire" for _, k in hits) and em.vetoed["fire"] >= 1
    hits, em = run_ai(frames, FakeAI(fire=0.9))             # the AI agrees: alarm
    assert any(k == "fire" for _, k in hits)
    assert em.last_info["fire"]["score"] >= 0.89


def test_smoke_needs_the_ai_to_agree():
    hits, _ = run_ai(smoke_frames(scene()), FakeAI(smoke=0.1))
    assert not any(k == "smoke" for _, k in hits)
    hits, _ = run_ai(smoke_frames(scene()), FakeAI(smoke=0.95))
    assert any(k == "smoke" for _, k in hits)


def test_ai_is_only_asked_when_the_rules_see_something():
    ai = FakeAI()
    run_ai([(i * 0.5, scene()) for i in range(20)], ai)
    assert ai.calls == 0


def test_real_ai_model_loads_and_scores():
    from cams.config import get_paths
    from cams.emergency import FireSmokeAI
    paths = get_paths()
    if not FireSmokeAI.available(paths.models):
        import pytest
        pytest.skip("MobileNetV2 not downloaded")
    ai = FireSmokeAI(paths.models)
    p = ai.probs(ai.features([scene(), np.full((200, 200, 3), 128, np.uint8)]))
    assert p.shape == (2, 3) and np.allclose(p.sum(1), 1, atol=1e-4)
    assert p[:, 1:].max() < 0.5                              # a corridor and a grey wall are not fire


# ------------------------------------------------------------------ person down: stricter (1.8)
def test_person_at_the_edge_or_unsure_is_not_down():
    bg = scene()
    edge = (0, 250, 180, 60)                                 # cut off by the left edge of the picture
    assert not run([(i * 0.5, bg) for i in range(80)], tracks=tracks_for(lambda t: edge))
    t = tracks_for(lambda t: LIE)

    def unsure(ts):
        out = t(ts)
        for tr in out:
            tr.score = 0.3                                   # the person finder is not sure it is a person
        return out
    assert not run([(i * 0.5, bg) for i in range(80)], tracks=unsure)


def test_pose_unsure_does_not_count_as_down():
    bg = scene()
    hits = run([(i * 0.5, bg) for i in range(80)], tracks=tracks_for(lambda t: LIE), tilt=lambda t: None)
    assert not hits                                           # pose AI installed but cannot see the body


def test_lying_on_a_bench_or_on_the_sports_field():
    from cams.emergency import EmergencyMonitor
    bg = scene()
    bench = (230, 240, 200, 80, 0.8, 13)
    assert not run([(i * 0.5, bg) for i in range(80)], tracks=tracks_for(lambda t: LIE), objects=[bench])
    em = EmergencyMonitor()
    tr = tracks_for(lambda t: LIE)
    hits = []
    for i in range(160):                                     # 80 seconds on a sports field
        ts = i * 0.5
        hits += [ts for k, _, _ in em.analyse(bg, ts, tr(ts), [LIE], [], RULES, "Field", field_place=True) if k == "person_down"]
    assert hits and 59 <= hits[0] <= 62                       # 3 x 20 seconds


def test_wrong_alarm_is_remembered(admin, system):
    cam = admin.post("/api/cameras", json={"name": "Kitchen", "source": "0", "kind": "usb"}).json()["id"]

    class W:
        id = cam

        class state:
            name = "Kitchen"

    from cams.activity import ActivityMonitor
    feat = np.random.default_rng(3).normal(size=1280).astype(np.float32)

    class SameAI(FakeAI):
        def features(self, crops):
            return np.repeat(feat[None], len(crops), axis=0)
    system.fire_ai = lambda: SameAI(fire=0.95)
    bg = scene()

    def burn(t0):
        mon = ActivityMonitor()
        system.emergency.pop(cam, None)
        for i in range(16):
            system._check_emergencies(W, flame(bg.copy(), 320, 300, 40, i * 0.5), t0 + i * 0.5, mon, [], [], parse_analytics(None), [])
        return [a for a in admin.get("/api/alerts").json() if a["kind"] == "fire" and not a["acknowledged"]]
    first = burn(1000)
    assert len(first) == 1
    r = admin.post(f"/api/alerts/{first[0]['id']}/wrong").json()
    assert r["learned"]
    assert admin.get("/api/alerts/emergencies").json() == []
    assert burn(5000) == []                                    # same picture again: no alarm
    # something different on the same camera still rings
    feat[:] = np.random.default_rng(9).normal(size=1280)
    assert len(burn(9000)) == 1
