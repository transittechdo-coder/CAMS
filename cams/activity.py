"""Suspicious-activity detection.

A small on-device AI model (NanoDet-Plus, trained on the COCO dataset) finds
people in each analysed frame, even when their face is not visible. A simple
tracker follows each person between frames. Rules then flag situations a
guard should look at:

* loitering     - someone stays in view of a camera longer than N minutes
* after hours   - anyone in view while the area is closed
* crowding      - N or more people together for a while
* running       - someone moves much faster than walking pace
* tampering     - the camera is covered, blurred or turned away
* bag left      - a backpack, handbag or suitcase stays in one place with nobody near it

These are *signals for a human to check*, not judgements about intent.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

NANODET_FILE = "object_detection_nanodet_2022nov.onnx"
INPUT = 416
PERSON = 0
# COCO classes that tell us what someone is doing (see behaviour.py)
OBJECT_CLASSES = {1, 13, 24, 25, 26, 28, 29, 32, 34, 35, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53,
                  54, 55, 56, 57, 59, 60, 62, 63, 64, 65, 66, 67, 71, 73, 76, 79}

DEFAULT_ANALYTICS = {
    "people": True,          # run person detection on this camera
    "loiter_minutes": 0,     # 0 = off
    "crowd_count": 0,        # 0 = off
    "running": False,
    "after_hours": "",       # e.g. "18:00-06:00"; empty = use the area's closed hours
    "tamper": True,
    # emergencies (see emergency.py): on for every camera unless turned off
    "fire": True,
    "smoke": True,
    "person_down": True,
    "down_seconds": 20,      # someone lying still this long = alert (sooner after a fall)
    "unattended_minutes": 0, # a bag left alone this long = alert; 0 = off
    "plates": False,         # read number plates (gate cameras)
    "plates_alert_unknown": False,   # alert for any plate not on the known list
}

BAG_CLASSES = {24: "backpack", 26: "handbag", 28: "suitcase"}
BAG_FORGET_S = 20            # a bag not seen for this long is forgotten (someone took it)

ALERT_COOLDOWN = 300         # seconds between two alerts of the same kind on one camera


def parse_analytics(raw: str | dict | None) -> dict:
    data = dict(DEFAULT_ANALYTICS)
    if isinstance(raw, str) and raw:
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if isinstance(raw, dict):
        data.update({k: v for k, v in raw.items() if k in DEFAULT_ANALYTICS})
    return data


def in_hours(spec: str, now: datetime | None = None) -> bool:
    """True if now falls inside 'HH:MM-HH:MM' (may cross midnight)."""
    if not spec or "-" not in spec:
        return False
    try:
        a, b = spec.split("-", 1)
        ah, am = (int(x) for x in a.strip().split(":"))
        bh, bm = (int(x) for x in b.strip().split(":"))
    except ValueError:
        return False
    now = now or datetime.now()
    t = now.hour * 60 + now.minute
    start, end = ah * 60 + am, bh * 60 + bm
    if start == end:
        return False
    return start <= t < end if start < end else (t >= start or t < end)


# ====================================================================== detector
class PersonDetector:
    """NanoDet-Plus 416x416 via OpenCV DNN, people only."""

    def __init__(self, models_dir: Path, threshold: float = 0.45):
        self.net = cv2.dnn.readNet(str(Path(models_dir) / NANODET_FILE))
        self.threshold = threshold
        self.strides = (8, 16, 32, 64)
        self.reg_max = 7
        self.project = np.arange(self.reg_max + 1, dtype=np.float32)
        self.mean = np.array([103.53, 116.28, 123.675], np.float32).reshape(1, 1, 3)
        self.std = np.array([57.375, 57.12, 58.395], np.float32).reshape(1, 1, 3)
        self.anchors = []
        for s in self.strides:
            n = INPUT // s
            xv, yv = np.meshgrid(np.arange(n) * s, np.arange(n) * s)
            self.anchors.append(np.column_stack((xv.ravel() + 0.5 * (s - 1), yv.ravel() + 0.5 * (s - 1))))

    @staticmethod
    def available(models_dir: Path) -> bool:
        return (Path(models_dir) / NANODET_FILE).is_file()

    def detect(self, frame: np.ndarray) -> list[tuple[int, int, int, int, float]]:
        return self.detect_scene(frame, objects=False)[0]

    def detect_scene(self, frame: np.ndarray, objects: bool = True, object_threshold: float = 0.35):
        """People, plus everyday objects near them (cups, plates, books, phones, balls...).

        Returns (people, objects); people are (x, y, w, h, score) and objects
        (x, y, w, h, score, coco_class). One forward pass of the network.
        """
        h, w = frame.shape[:2]
        scale = INPUT / max(h, w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        canvas = np.zeros((INPUT, INPUT, 3), np.uint8)
        top, left = (INPUT - nh) // 2, (INPUT - nw) // 2
        canvas[top:top + nh, left:left + nw] = cv2.resize(frame, (nw, nh))
        blob = cv2.dnn.blobFromImage((canvas.astype(np.float32) - self.mean) / self.std)
        self.net.setInput(blob)
        outs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        # Output order differs between OpenCV versions: sort by kind and grid size.
        cls_outs = sorted((o for o in outs if o.shape[-1] == 80), key=lambda o: -o.shape[-2])
        box_outs = sorted((o for o in outs if o.shape[-1] == 4 * (self.reg_max + 1)), key=lambda o: -o.shape[-2])
        pboxes, pscores, oboxes, oscores, oclasses = [], [], [], [], []
        obj_cols = np.array(sorted(OBJECT_CLASSES), dtype=int)
        for stride, cls, reg, anchors in zip(self.strides, cls_outs, box_outs, self.anchors):
            cls = cls.reshape(-1, cls.shape[-1])
            if len(anchors) != len(cls):
                continue
            reg = reg.reshape(-1, 4 * (self.reg_max + 1))
            person = cls[:, PERSON]
            keep_p = person > self.threshold * 0.8
            if objects:
                obj = cls[:, obj_cols]
                best = obj.argmax(axis=1)
                best_score = obj[np.arange(len(obj)), best]
                keep_o = best_score > object_threshold
            else:
                keep_o = np.zeros(len(cls), bool)
            keep = keep_p | keep_o
            if not keep.any():
                continue
            r = reg[keep].reshape(-1, self.reg_max + 1)
            e = np.exp(r - r.max(axis=1, keepdims=True))
            dist = ((e / e.sum(axis=1, keepdims=True)) @ self.project).reshape(-1, 4) * stride
            a = anchors[keep]
            x1, y1 = a[:, 0] - dist[:, 0], a[:, 1] - dist[:, 1]
            x2, y2 = a[:, 0] + dist[:, 2], a[:, 1] + dist[:, 3]
            bx = np.column_stack((x1, y1, x2 - x1, y2 - y1))
            kp, ko = keep_p[keep], keep_o[keep]
            if kp.any():
                pboxes.append(bx[kp]); pscores.append(person[keep][kp])
            if ko.any():
                oboxes.append(bx[ko]); oscores.append(best_score[keep][ko]); oclasses.append(obj_cols[best[keep][ko]])

        def unpad(x, y, bw, bh):
            x0 = max(0, int((x - left) / scale))
            y0 = max(0, int((y - top) / scale))
            x1 = min(w, int((x + bw - left) / scale))
            y1 = min(h, int((y + bh - top) / scale))
            return x0, y0, x1 - x0, y1 - y0

        people = []
        if pboxes:
            boxes, scores = np.concatenate(pboxes), np.concatenate(pscores)
            idx = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self.threshold, 0.5)
            for i in np.array(idx).reshape(-1):
                x0, y0, bw, bh = unpad(*boxes[i])
                if bw > 8 and bh > 16:
                    people.append((x0, y0, bw, bh, float(scores[i])))
        found = []
        if oboxes:
            boxes, scores, classes = np.concatenate(oboxes), np.concatenate(oscores), np.concatenate(oclasses)
            idx = cv2.dnn.NMSBoxesBatched(boxes.tolist(), scores.tolist(), classes.tolist(), object_threshold, 0.5) \
                if hasattr(cv2.dnn, "NMSBoxesBatched") else cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), object_threshold, 0.5)
            for i in np.array(idx).reshape(-1)[:40]:
                x0, y0, bw, bh = unpad(*boxes[i])
                if bw > 3 and bh > 3:
                    found.append((x0, y0, bw, bh, float(scores[i]), int(classes[i])))
        return people, found


# ====================================================================== tracker
@dataclass
class Track:
    id: int
    box: tuple[int, int, int, int]
    first_seen: float
    last_seen: float
    history: list[tuple[float, float, float, float]] = field(default_factory=list)  # t, cx, cy, height
    flagged: set = field(default_factory=set)
    score: float = 1.0                     # how sure the person finder was, last time

    @property
    def dwell(self) -> float:
        return self.last_seen - self.first_seen

    def speed(self, window: float = 2.5) -> float:
        """Typical speed in body heights per second over the last `window` seconds.

        Uses the median of step speeds so one bad match between two people
        crossing paths cannot fake a sprint. Walking is about 0.5-1 heights/s,
        running about 2-4.
        """
        pts = [p for p in self.history if p[0] >= self.last_seen - window]
        if len(pts) < 5 or pts[-1][0] - pts[0][0] < 1.2:
            return 0.0
        steps = []
        for (t0, x0, y0, h0), (t1, x1, y1, h1) in zip(pts, pts[1:]):
            if t1 - t0 <= 0:
                continue
            steps.append(math.hypot(x1 - x0, y1 - y0) / max(20.0, (h0 + h1) / 2) / (t1 - t0))
        if len(steps) < 4:
            return 0.0
        steps.sort()
        return steps[len(steps) // 2]


def _iou(a, b) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


class Tracker:
    def __init__(self, max_gap: float = 6.0):
        self.tracks: dict[int, Track] = {}
        self.next_id = 1
        self.max_gap = max_gap

    def update(self, boxes: list[tuple], ts: float) -> list[Track]:
        live = [t for t in self.tracks.values() if ts - t.last_seen <= self.max_gap]
        self.tracks = {t.id: t for t in live}
        used: set[int] = set()
        for b in boxes:
            box = tuple(int(v) for v in b[:4])
            cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
            best, best_score = None, 0.0
            for t in live:
                if t.id in used:
                    continue
                s = _iou(t.box, box)
                if s < 0.1:  # allow fast movers: match by distance relative to body height
                    tcx, tcy = t.box[0] + t.box[2] / 2, t.box[1] + t.box[3] / 2
                    d = math.hypot(cx - tcx, cy - tcy) / max(20, t.box[3])
                    s = 0.3 - 0.15 * d if d < 1.6 else 0
                if s > best_score:
                    best, best_score = t, s
            if best is None:
                best = Track(self.next_id, box, ts, ts)
                self.next_id += 1
                self.tracks[best.id] = best
            used.add(best.id)
            best.box = box
            best.last_seen = ts
            if len(b) > 4:
                best.score = float(b[4])
            best.history.append((ts, cx, cy, box[3]))
            best.history = best.history[-60:]
        return [self.tracks[i] for i in used]


# ====================================================================== bags left behind
class UnattendedCheck:
    """Bags (backpack, handbag, suitcase) that stay in one place with nobody near them."""

    def __init__(self):
        self.bags: list[dict] = []
        self.next_id = 1

    @staticmethod
    def _near(bag, people) -> bool:
        bx, by, bw, bh = bag[:4]
        for p in people or []:
            px, py, pw, ph = p[:4]
            mx, my = max(pw, ph * 0.6), ph * 0.25          # about an arm's reach around the person
            if bx < px + pw + mx and bx + bw > px - mx and by < py + ph + my and by + bh > py - my:
                return True
        return False

    def update(self, objects, people, ts: float, minutes: float) -> list[dict]:
        found = [o for o in (objects or []) if len(o) > 5 and o[5] in BAG_CLASSES]
        used: set[int] = set()
        for o in found:
            box = tuple(int(v) for v in o[:4])
            cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
            best = None
            for b in self.bags:
                if b["id"] in used:
                    continue
                d = math.hypot(cx - b["cx"], cy - b["cy"]) / max(8, b["box"][2], b["box"][3])
                if d < 0.6 and (best is None or d < best[0]):
                    best = (d, b)
            if best is None:
                b = {"id": self.next_id, "box": box, "cx": cx, "cy": cy, "kind": BAG_CLASSES[o[5]],
                     "first": ts, "seen": ts, "alone_since": None, "alerted": False}
                self.next_id += 1
                self.bags.append(b)
            else:
                b = best[1]
                b["box"], b["seen"] = box, ts
            used.add(b["id"])
            if self._near(box, people):
                b["alone_since"] = None
                b["alerted"] = False
            elif b["alone_since"] is None:
                b["alone_since"] = ts
        self.bags = [b for b in self.bags if ts - b["seen"] <= BAG_FORGET_S]
        out = []
        if minutes <= 0:
            return out
        for b in self.bags:
            if b["alone_since"] is not None and not b["alerted"] and ts - b["alone_since"] >= minutes * 60:
                b["alerted"] = True
                out.append(b)
        return out


# ====================================================================== tamper
class TamperCheck:
    """Notices when a camera is covered, defocused or turned away."""

    def __init__(self):
        self.reference: np.ndarray | None = None
        self.ref_sharp = 0.0
        self.ref_at = 0.0
        self.bad_since: float | None = None
        self.reason = ""

    def update(self, frame: np.ndarray, ts: float, people_in_view: int) -> str | None:
        small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
        std = float(small.std())
        sharp = float(cv2.Laplacian(small, cv2.CV_64F).var())
        reason = ""
        if std < 7:
            reason = "covered or showing a blank picture"
        elif self.reference is not None:
            if self.ref_sharp > 40 and sharp < self.ref_sharp * 0.2:
                reason = "picture has become blurred"
            else:
                diff = float(np.mean(cv2.absdiff(small, self.reference)))
                if diff > 45 and people_in_view == 0:
                    reason = "view has changed (camera moved or turned)"
        if not reason:
            self.bad_since = None
            # adopt a new reference slowly, only from good, empty frames
            if self.reference is None or (ts - self.ref_at > 120 and people_in_view == 0):
                self.reference, self.ref_sharp, self.ref_at = small, sharp, ts
            return None
        if self.bad_since is None:
            self.bad_since, self.reason = ts, reason
        if ts - self.bad_since >= 15:
            return self.reason
        return None


# ====================================================================== monitor
class ActivityMonitor:
    """Per-camera state; `analyse` returns new events [(kind, message)]."""

    def __init__(self):
        self.tracker = Tracker()
        self.tamper = TamperCheck()
        self.bags = UnattendedCheck()
        self.last_alert: dict[str, float] = {}
        self.crowd_since: float | None = None
        self.people: list[tuple] = []
        self.bag_box = None

    def _ready(self, kind: str, ts: float) -> bool:
        if ts - self.last_alert.get(kind, 0) < ALERT_COOLDOWN:
            return False
        self.last_alert[kind] = ts
        return True

    def analyse(self, frame, ts: float, people: list[tuple], rules: dict, closed_hours: str, cam_name: str, objects=None):
        events: list[tuple[str, str]] = []
        self.people = people
        tracks = self.tracker.update(people, ts) if people is not None else []
        n = len(people or [])

        if rules.get("tamper", True):
            r = self.tamper.update(frame, ts, n)
            if r and self._ready("tamper", ts):
                events.append(("tamper", f"Camera {cam_name}: {r}"))

        hours = rules.get("after_hours") or closed_hours
        if n and hours and in_hours(hours) and self._ready("after_hours", ts):
            events.append(("after_hours", f"{n} person{'s' if n > 1 else ''} at {cam_name} during closed hours ({hours})"))

        lm = float(rules.get("loiter_minutes") or 0)
        if lm > 0:
            for t in tracks:
                if t.dwell >= lm * 60 and "loiter" not in t.flagged:
                    t.flagged.add("loiter")
                    if self._ready(f"loiter-{t.id}", ts):
                        events.append(("loitering", f"Someone has stayed at {cam_name} for {int(t.dwell // 60)} minutes"))

        cc = int(rules.get("crowd_count") or 0)
        if cc > 0:
            if n >= cc:
                self.crowd_since = self.crowd_since or ts
                if ts - self.crowd_since >= 10 and self._ready("crowd", ts):
                    events.append(("crowd", f"{n} people gathered at {cam_name}"))
            else:
                self.crowd_since = None

        um = float(rules.get("unattended_minutes") or 0)
        if um > 0:
            for b in self.bags.update(objects, people, ts, um):
                if self._ready(f"bag-{b['id']}", ts):
                    mins = int((ts - b["alone_since"]) // 60)
                    self.bag_box = b["box"]
                    events.append(("bag_left", f"A {b['kind']} has been left alone at {cam_name} for {mins} minute{'s' if mins != 1 else ''}. Check it."))

        if rules.get("running"):
            for t in tracks:
                if t.speed() > 2.0 and "run" not in t.flagged:
                    t.flagged.add("run")
                    if self._ready("running", ts):
                        events.append(("running", f"Someone running at {cam_name}"))
        return events
