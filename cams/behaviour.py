"""Activity AI: what each recognised person is doing, written into their timeline.

How it decides, for every recognised person, about every 2 seconds:

1. Body pose   - MediaPipe Pose (on-device) gives 33 body points in 3D metres:
                 knee and hip angles (sitting / standing), how upright the body
                 is (lying), hands near the mouth (eating, drinking), a hand
                 raised, head down (reading, writing).
2. Things      - the object detector already finds cups, plates, spoons,
                 food, books, phones, laptops, balls, chairs, beds and tables
                 near the person or in their hands.
3. Movement    - speed from the person tracker (walking, running).
4. Place       - what the map area is used for (dining hall, classroom...).

These become one list of numbers (a "feature vector"). Three layers turn it
into an activity, the first that answers wins:

* the admin's place-and-time rules ("Chapel 7:00-7:30 = Morning assembly")
* activities the admin taught CAMS from example pictures (nearest-neighbour
  vote over the labelled examples - this is the part that learns)
* built-in knowledge (eating, sitting, walking, running, reading, ...)

Everything runs on the PC; nothing is sent anywhere.
"""

from __future__ import annotations

import json
import math
import threading
import time
import uuid
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .activity import in_hours

POSE_FILE = "pose_estimation_mediapipe_2023mar.onnx"
SAMPLE_EVERY = 2.0          # seconds between two looks at the same person
MIN_POSE_HEIGHT = 70        # pixels; smaller people get no pose (too few details)

# ------------------------------------------------------------------ vocabulary
BUILTIN = {
    "eating": "Eating or drinking",
    "sitting": "Sitting",
    "standing": "Standing",
    "walking": "Walking",
    "running": "Running",
    "lying": "Lying down",
    "sleeping": "Sleeping or resting",
    "reading": "Reading or writing",
    "phone": "Using a phone",
    "computer": "Using a computer",
    "sport": "Playing sport",
    "hand_up": "Raising a hand",
    "group": "With a group",
}

PURPOSES = {
    "": "Not set",
    "dining": "Dining hall / eating",
    "classroom": "Classroom",
    "lab": "Laboratory",
    "library": "Library / study",
    "dormitory": "Dormitory / sleeping",
    "sports": "Sports ground",
    "worship": "Chapel / mosque / prayer",
    "assembly": "Assembly / hall",
    "office": "Office / staff room",
    "gate": "Gate / entrance",
    "outdoor": "Outdoor / walkway",
    "other": "Other",
}
PURPOSE_KEYS = [k for k in PURPOSES if k]

# words in an area's name that tell us what it is for (when the admin has not said)
PURPOSE_WORDS = [
    ("dining", ("dining", " dh", "dh ", "canteen", "cafeteria", "mess", "kitchen", "chakula", "bwalo")),
    ("library", ("library", "maktaba", "study", "prep")),
    ("lab", ("lab", "maabara", "workshop")),
    ("classroom", ("class", "form ", "darasa", "lecture", "room ")),
    ("dormitory", ("dorm", "hostel", "bweni", "house")),
    ("sports", ("field", "pitch", "court", "ground", "uwanja", "gym", "sport")),
    ("worship", ("chapel", "church", "mosque", "msikiti", "kanisa", "prayer")),
    ("assembly", ("assembly", "hall", "parade")),
    ("office", ("office", "staff", "admin", "ofisi", "head")),
    ("gate", ("gate", "lango", "entrance", "reception")),
]


def guess_purpose(name: str) -> str:
    n = f" {name.lower()} "
    for key, words in PURPOSE_WORDS:
        if any(w in n for w in words):
            return key
    return ""


# COCO class groups (index in the 80-class list)
GROUPS = {
    "food": {45, 42, 43, 44, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55},   # bowl, cutlery, food
    "drink": {39, 40, 41},                                                # bottle, glass, cup
    "table": {60},
    "seat": {56, 57, 13},                                                 # chair, couch, bench
    "bed": {59},
    "phone": {67, 65},                                                    # phone, remote
    "computer": {63, 64, 66, 62},                                         # laptop, mouse, keyboard, tv
    "book": {73},
    "ball": {32, 29, 34, 35, 38},                                         # ball, frisbee, bat, glove, racket
    "bag": {24, 26, 28},
    "bicycle": {1},
    "wash": {71, 79},                                                     # sink, toothbrush
}
GROUP_KEYS = list(GROUPS)
IN_HAND = ("food", "drink", "phone", "book")

FEATURE_NAMES = (
    ["knee_l", "knee_r", "hip_l", "hip_r", "elbow_l", "elbow_r", "tilt", "hand_mouth", "hand_up", "head_down",
     "legs_seen", "pose_ok", "aspect", "speed", "moving", "near_people"]
    + [f"near_{g}" for g in GROUP_KEYS] + [f"hand_{g}" for g in IN_HAND] + [f"place_{p}" for p in PURPOSE_KEYS]
)
# how much each part counts when comparing with taught examples
WEIGHTS = np.array(
    [1.2, 1.2, 1.4, 1.4, 0.6, 0.6, 1.6, 1.2, 0.8, 0.8, 0.3, 0.3, 1.0, 1.6, 1.0, 0.6]
    + [0.9] * len(GROUP_KEYS) + [1.1] * len(IN_HAND) + [0.7] * len(PURPOSE_KEYS), np.float32)


# ------------------------------------------------------------------ pose
class PoseEstimator:
    """MediaPipe Pose (opencv_zoo build) on one person crop."""

    def __init__(self, models_dir: Path):
        self.net = cv2.dnn.readNet(str(Path(models_dir) / POSE_FILE))
        self.names = self.net.getUnconnectedOutLayersNames()

    @staticmethod
    def available(models_dir: Path) -> bool:
        return (Path(models_dir) / POSE_FILE).is_file()

    def estimate(self, frame: np.ndarray, box) -> dict | None:
        x, y, w, h = box[:4]
        if h < MIN_POSE_HEIGHT:
            return None
        side = int(max(w, h) * 1.3)
        cx, cy = x + w / 2, y + h / 2
        x0, y0 = int(cx - side / 2), int(cy - side / 2)
        H, W = frame.shape[:2]
        crop = np.zeros((side, side, 3), np.uint8)
        sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + side), min(H, y0 + side)
        if sx1 <= sx0 or sy1 <= sy0:
            return None
        crop[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = frame[sy0:sy1, sx0:sx1]
        blob = cv2.cvtColor(cv2.resize(crop, (256, 256), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        self.net.setInput(blob[np.newaxis])
        outs = dict(zip(self.names, self.net.forward(self.names)))
        lm = conf = world = None
        for o in outs.values():
            if o.shape == (1, 195):
                lm = o[0].reshape(39, 5)
            elif o.shape == (1, 1):
                conf = float(o[0][0])
            elif o.shape == (1, 117):
                world = o[0].reshape(39, 3)
        if lm is None or world is None or conf is None or conf < 0.5:
            return None
        vis = 1 / (1 + np.exp(-lm[:33, 3]))
        img = lm[:33, :2] * (side / 256.0) + np.array([x0, y0], np.float32)
        return {"world": world[:33], "image": img, "vis": vis, "conf": conf}


def _angle(a, b, c) -> float:
    """Angle at b (degrees) between a-b and c-b."""
    v1, v2 = a - b, c - b
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    if n < 1e-6:
        return 180.0
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1, 1))))


# ------------------------------------------------------------------ features
def _overlap(person_box, obj_box, grow: float = 0.3) -> float:
    """Share of the object that lies inside the (slightly enlarged) person box."""
    x, y, w, h = person_box[:4]
    x -= w * grow; y -= h * grow * 0.5; w *= 1 + 2 * grow; h *= 1 + grow
    ox, oy, ow, oh = obj_box[:4]
    ix = max(0, min(x + w, ox + ow) - max(x, ox))
    iy = max(0, min(y + h, oy + oh) - max(y, oy))
    return ix * iy / max(1.0, ow * oh)


def features(box, pose: dict | None, objects: list, speed: float, near_people: int, purpose: str) -> np.ndarray:
    f = dict.fromkeys(FEATURE_NAMES, 0.0)
    x, y, w, h = box[:4]
    if pose is not None:
        P, V = pose["world"], pose["vis"]
        f["knee_l"] = _angle(P[23], P[25], P[27]) / 180
        f["knee_r"] = _angle(P[24], P[26], P[28]) / 180
        f["hip_l"] = _angle(P[11], P[23], P[25]) / 180
        f["hip_r"] = _angle(P[12], P[24], P[26]) / 180
        f["elbow_l"] = _angle(P[11], P[13], P[15]) / 180
        f["elbow_r"] = _angle(P[12], P[14], P[16]) / 180
        sh, hp = (P[11] + P[12]) / 2, (P[23] + P[24]) / 2
        torso = sh - hp
        f["tilt"] = float(np.degrees(np.arccos(np.clip(abs(torso[1]) / (np.linalg.norm(torso) + 1e-6), 0, 1)))) / 90
        mouth = (P[9] + P[10]) / 2
        f["hand_mouth"] = float(min(1.0, min(np.linalg.norm(P[15] - mouth), np.linalg.norm(P[16] - mouth))))
        # image y grows downwards: a wrist above the top of the head
        I = pose["image"]
        head_top = min(I[0][1], I[2][1], I[5][1])
        f["hand_up"] = 1.0 if (min(I[15][1], I[16][1]) < head_top - 0.05 * h and max(V[15], V[16]) > 0.5) else 0.0
        # 0 = head up (nose well above the shoulders), 1 = nose down at shoulder level
        f["head_down"] = float(np.clip((I[0][1] - (I[11][1] + I[12][1]) / 2) / max(1, h) * 6 + 1, 0, 1))
        f["legs_seen"] = float(np.mean(V[[25, 26, 27, 28]]))
        f["pose_ok"] = 1.0
        wrists = [I[15], I[16]]
    else:
        for k in ("knee_l", "knee_r", "hip_l", "hip_r", "elbow_l", "elbow_r"):
            f[k] = 0.75
        f["hand_mouth"], f["head_down"] = 0.6, 0.5
        wrists = []
    f["aspect"] = float(min(3.0, w / max(1, h)))
    f["speed"] = float(min(4.0, speed)) / 4
    f["moving"] = 1.0 if speed > 0.35 else 0.0
    f["near_people"] = min(5, near_people) / 5
    for o in objects:
        cls = o[5]
        g = next((k for k, v in GROUPS.items() if cls in v), None)
        if not g:
            continue
        if _overlap(box, o) > 0.3:
            f[f"near_{g}"] = 1.0
            if g in IN_HAND and wrists:
                ocx, ocy = o[0] + o[2] / 2, o[1] + o[3] / 2
                if min(math.hypot(ocx - wx, ocy - wy) for wx, wy in wrists) < 0.18 * h + max(o[2], o[3]) / 2:
                    f[f"hand_{g}"] = 1.0
    if purpose in PURPOSE_KEYS:
        f[f"place_{purpose}"] = 1.0
    return np.array([f[k] for k in FEATURE_NAMES], np.float32)


def as_dict(vec) -> dict:
    return {k: float(v) for k, v in zip(FEATURE_NAMES, vec)}


# ------------------------------------------------------------------ built-in knowledge
def builtin_activity(vec) -> tuple[str, float]:
    f = as_dict(vec)
    speed = f["speed"] * 4
    knees = (f["knee_l"] + f["knee_r"]) / 2 * 180
    hips = (f["hip_l"] + f["hip_r"]) / 2 * 180
    pose = f["pose_ok"] > 0.5
    lying = (pose and f["tilt"] > 0.62) or (not pose and f["aspect"] > 1.35 and speed < 0.3)
    sitting = (pose and f["legs_seen"] > 0.4 and (hips < 125 or knees < 120)) or (f["near_seat"] and speed < 0.3 and f["aspect"] > 0.55)
    eating_place = f["place_dining"] > 0

    if lying:
        return ("sleeping", 0.7) if (f["near_bed"] or f["place_dormitory"]) else ("lying", 0.65)
    if speed > 2.0:
        return ("sport", 0.65) if f["near_ball"] or f["place_sports"] else ("running", 0.75)
    if f["near_ball"] and (speed > 0.35 or not f["near_seat"]):
        return "sport", 0.6
    if f["hand_food"] or f["hand_drink"] or ((f["near_food"] or f["near_drink"]) and f["hand_mouth"] < 0.25):
        return "eating", 0.8
    if pose and f["hand_mouth"] < 0.12 and (f["near_food"] or f["near_drink"] or f["near_table"] or eating_place):
        return "eating", 0.7
    if eating_place and (f["near_food"] or f["near_drink"]) and speed < 0.35:
        return "eating", 0.6
    if f["hand_phone"]:
        return "phone", 0.75
    if f["hand_up"] and speed < 0.35:
        return "hand_up", 0.65
    if f["near_computer"] and speed < 0.35:
        return "computer", 0.6
    if f["hand_book"] or (f["near_book"] and speed < 0.35):
        return "reading", 0.65
    if sitting and f["head_down"] > 0.7 and (f["place_classroom"] or f["place_library"] or f["place_lab"]):
        return "reading", 0.5
    if f["near_phone"] and speed < 0.35:
        return "phone", 0.5
    if speed > 0.35:
        return "walking", 0.7
    if sitting:
        return ("eating", 0.45) if eating_place and f["near_table"] else ("sitting", 0.65)
    if f["near_people"] >= 0.4:
        return "group", 0.5
    return "standing", 0.55


# ------------------------------------------------------------------ taught knowledge
class TaughtModel:
    """Nearest-neighbour vote over the examples the admin labelled."""

    def __init__(self):
        self.X = np.zeros((0, len(FEATURE_NAMES)), np.float32)
        self.y: list[str] = []
        self.counts: Counter = Counter()

    def load(self, rows: list[dict]) -> None:
        X, y = [], []
        for r in rows:
            try:
                v = np.array(json.loads(r["features"]), np.float32)
            except (ValueError, TypeError):
                continue
            if v.shape == (len(FEATURE_NAMES),) and r["label"]:
                X.append(v * WEIGHTS)
                y.append(r["label"])
        self.X = np.array(X, np.float32) if X else np.zeros((0, len(FEATURE_NAMES)), np.float32)
        self.y = y
        self.counts = Counter(y)

    def predict(self, vec) -> tuple[str, float] | None:
        if len(self.y) < 3:
            return None
        d = np.linalg.norm(self.X - vec * WEIGHTS, axis=1)
        k = min(7, len(self.y))
        idx = np.argsort(d)[:k]
        if d[idx[0]] > 1.6:                 # nothing taught looks like this
            return None
        votes: Counter = Counter()
        for i in idx:
            votes[self.y[i]] += 1.0 / (0.15 + d[i])
        label, score = votes.most_common(1)[0]
        share = score / sum(votes.values())
        if self.counts[label] < 3 or share < 0.6:
            return None
        return label, round(min(0.95, share * (1.2 - min(1.0, d[idx[0]]) * 0.4)), 2)


# ------------------------------------------------------------------ admin place/time rules
def rule_activity(rules: list[dict], area_ids: set, purposes: set, base: str, now: datetime | None = None) -> str | None:
    now = now or datetime.now()
    for r in rules:
        if not r.get("enabled", 1):
            continue
        days = r.get("days") or []
        if days and now.weekday() not in days:
            continue
        if not in_hours(f"{r['start']}-{r['end']}", now):
            continue
        areas = set(r.get("area_ids") or [])
        if areas and not (areas & area_ids):
            continue
        if not areas and r.get("purpose") and r["purpose"] not in purposes:
            continue
        body = r.get("body") or "any"
        if body == "sitting" and base not in ("sitting", "eating", "reading", "computer", "phone", "hand_up"):
            continue
        if body == "standing" and base not in ("standing", "group", "hand_up"):
            continue
        if body == "moving" and base not in ("walking", "running", "sport"):
            continue
        return r["activity"]
    return None


# ------------------------------------------------------------------ per camera
class BehaviourWatcher:
    """Links people (body boxes) to recognised faces and samples what they do."""

    def __init__(self):
        self.ident: dict[int, dict] = {}        # track id -> {"pid", "ts"}
        self.last_sample: dict[int, float] = {}
        self.recent: dict[int, deque] = {}     # track id -> recent labels (smoothing)

    def link_faces(self, tracks, faces, ts: float) -> None:
        for f in faces:
            if f.person_id is None:
                continue
            fx, fy, fw, fh = f.box
            cx, cy = fx + fw / 2, fy + fh / 2
            best, best_d = None, 1e9
            for t in tracks:
                x, y, w, h = t.box
                if x <= cx <= x + w and y - 0.1 * h <= cy <= y + 0.45 * h:
                    d = abs(cx - (x + w / 2)) + abs(cy - (y + 0.12 * h))
                    if d < best_d:
                        best, best_d = t, d
            if best is not None:
                self.ident[best.id] = {"pid": f.person_id, "ts": ts}
        live = {t.id for t in tracks}
        for tid in [k for k in self.ident if k not in live and ts - self.ident[k]["ts"] > 30]:
            self.ident.pop(tid, None); self.recent.pop(tid, None); self.last_sample.pop(tid, None)

    def due(self, tracks, ts: float, every: float = SAMPLE_EVERY):
        for t in tracks:
            if t.id in self.ident and t.last_seen == ts and ts - self.last_sample.get(t.id, 0) >= every:
                self.last_sample[t.id] = ts
                yield t, self.ident[t.id]["pid"]

    def smooth(self, track_id: int, label: str) -> str:
        q = self.recent.setdefault(track_id, deque(maxlen=3))
        q.append(label)
        top, n = Counter(q).most_common(1)[0]
        return top if n >= 2 else label


# ------------------------------------------------------------------ the engine
class BehaviourEngine:
    """Owned by CamsSystem. Thread-safe; the recognition workers call `observe`."""

    def __init__(self, db, paths, models_dir: Path):
        self.db = db
        self.paths = paths
        self._local = threading.local()
        self.models_dir = models_dir
        self.pose_ok = False
        if PoseEstimator.available(models_dir):
            try:                       # load once now so a broken model shows up in the status
                self._local.pose = PoseEstimator(models_dir)
                self.pose_ok = True
            except Exception:
                self.pose_ok = False
        self.taught = TaughtModel()
        self.rules: list[dict] = []
        self.watchers: dict[int, BehaviourWatcher] = {}
        self._open: dict[int, dict] = {}        # person id -> open timeline entry
        self._lock = threading.Lock()
        self.reload()

    def pose(self):
        if not self.pose_ok:
            return None
        p = getattr(self._local, "pose", None)
        if p is None:
            try:
                p = self._local.pose = PoseEstimator(self.models_dir)
            except Exception:
                self.pose_ok = False
                return None
        return p

    def reload(self) -> None:
        self.taught.load(self.db.query("SELECT features, label FROM activity_examples WHERE label IS NOT NULL AND label != ''"))
        rules = []
        for r in self.db.query("SELECT * FROM activity_rules WHERE enabled = 1 ORDER BY id"):
            r = dict(r)
            r["area_ids"] = json.loads(r.get("area_ids") or "[]")
            r["days"] = json.loads(r.get("days") or "[]")
            rules.append(r)
        self.rules = rules

    def labels(self) -> dict[str, str]:
        out = dict(BUILTIN)
        for r in self.db.query("SELECT key, label FROM activity_types ORDER BY label"):
            out[r["key"]] = r["label"]
        for r in self.rules:
            out.setdefault(r["activity"], r["activity"])
        return out

    def classify(self, vec, area_ids: set, purposes: set, now: datetime | None = None) -> tuple[str, str, float]:
        base, conf = builtin_activity(vec)
        taught = self.taught.predict(vec)
        label, source = (taught[0], "taught") if taught else (base, "ai")
        if taught:
            conf = taught[1]
        ruled = rule_activity(self.rules, area_ids, purposes, base, now)
        if ruled:
            return ruled, "rule", 0.9
        return label, source, conf

    # called from recognition workers -------------------------------------------
    def observe(self, cam: dict, frame: np.ndarray, ts: float, tracks, faces, objects: list, areas: list[dict], all_boxes) -> int:
        """Look at every recognised person on this camera. Returns how many were sampled."""
        w = self.watchers.setdefault(cam["id"], BehaviourWatcher())
        w.link_faces(tracks, faces, ts)
        area = areas[0] if areas else None
        purposes = {a.get("purpose") or guess_purpose(a["name"]) for a in areas} - {""}
        purpose = next(iter(purposes), "")
        area_ids = {a["id"] for a in areas}
        n = 0
        for t, pid in list(w.due(tracks, ts))[:6]:
            pose = None
            est = self.pose()
            if est is not None:
                try:
                    pose = est.estimate(frame, t.box)
                except cv2.error:
                    pose = None
            x, y, bw, bh = t.box
            near = sum(1 for b in all_boxes if b[:4] != t.box and math.hypot((b[0] + b[2] / 2) - (x + bw / 2), (b[1] + b[3] / 2) - (y + bh / 2)) < 1.5 * bh)
            vec = features(t.box, pose, objects, t.speed(), near, purpose)
            label, source, conf = self.classify(vec, area_ids, purposes)
            if source != "rule":
                label = w.smooth(t.id, label)
            self.record(pid, cam, area, label, source, conf, ts, frame, t.box, vec)
            n += 1
        return n

    def record(self, pid: int, cam: dict, area: dict | None, label: str, source: str, conf: float, ts: float,
               frame: np.ndarray | None, box, vec) -> None:
        merge = 90.0
        with self._lock:
            cur = self._open.get(pid)
            if cur and cur["activity"] == label and cur["camera_id"] == cam["id"] and ts - cur["end"] <= merge:
                cur["end"] = ts
                cur["samples"] += 1
                cur["conf"] = max(cur["conf"], conf)
                if ts - cur["saved"] >= 10:
                    cur["saved"] = ts
                    self.db.execute("UPDATE activity_log SET end_ts = ?, samples = ?, confidence = ? WHERE id = ?",
                                    (ts, cur["samples"], cur["conf"], cur["id"]))
                return
            if cur:  # close the previous entry exactly
                self.db.execute("UPDATE activity_log SET end_ts = ?, samples = ? WHERE id = ?", (cur["end"], cur["samples"], cur["id"]))
        image = self._save_crop(frame, box) if frame is not None else None
        eid = self.db.execute(
            "INSERT INTO activity_examples(ts, camera_id, person_id, features, auto_label, image_path) VALUES (?,?,?,?,?,?)",
            (ts, cam["id"], pid, json.dumps([round(float(v), 4) for v in vec]), label, image))
        sid = self.db.execute(
            "INSERT INTO activity_log(person_id, camera_id, camera_name, area_id, area_name, activity, source, confidence, "
            "start_ts, end_ts, samples, image_path, example_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, cam["id"], cam.get("name", ""), area["id"] if area else None, area["name"] if area else "",
             label, source, conf, ts, ts, 1, image, eid))
        with self._lock:
            self._open[pid] = {"id": sid, "activity": label, "camera_id": cam["id"], "end": ts, "saved": ts, "samples": 1, "conf": conf}

    def _save_crop(self, frame: np.ndarray, box) -> str | None:
        x, y, w, h = box[:4]
        pad = int(0.08 * h)
        H, W = frame.shape[:2]
        crop = frame[max(0, y - pad):min(H, y + h + pad), max(0, x - pad):min(W, x + w + pad)]
        if crop.size == 0:
            return None
        if crop.shape[0] > 320:
            crop = cv2.resize(crop, (int(crop.shape[1] * 320 / crop.shape[0]), 320))
        day = time.strftime("%Y%m%d", time.localtime())
        folder = self.paths.snapshots / day
        folder.mkdir(parents=True, exist_ok=True)
        name = f"act_{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(folder / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return f"{day}/{name}"
