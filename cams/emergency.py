"""Emergency detection: fire, heavy smoke and a person lying on the ground.

These run on the pictures the recognition workers already analyse, on this PC,
without internet and without extra AI downloads:

* **Fire** - areas with flame colours (red, orange, yellow; very bright white on
  black-and-white night cameras) that *flicker*: the shape of a flame changes
  from one picture to the next, while an orange wall, a red car or a lamp stays
  the same. The area must stay in the same place for a few seconds, so a person
  in an orange shirt walking past does not count.
* **Heavy smoke** - a grey haze that hides what the camera normally sees: in
  part of the picture the details (edges, lines, texture) fade and the colours
  turn grey, compared with how that view usually looks. It has to cover a good
  part of the picture for several seconds. A sudden change of the whole picture
  (lights switched off, the camera turning to night mode) is not smoke: CAMS
  simply learns the new view.
* **Person down** - the person-detection AI finds the person even when their
  face cannot be seen. When the body pose AI is installed it measures how much
  the body leans; otherwise it uses the shape of the person (wider than tall).
  Someone lying still for longer than the set time (20 seconds) raises an alert,
  sooner after a fall (standing, then suddenly lying). Beds and sofas, and
  sleeping places (dormitories), do not count.

These are warnings for a person to check at once. They never replace smoke
detectors, fire alarms or a first-aid plan.
"""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

W = 320                       # pictures are checked at this width (fast)
GRID = (16, 9)                # smoke is checked in 16 x 9 squares

# sensitivity -> (fire seconds, fire min area %, smoke seconds, smoke min cover %)
SENSITIVITY = {
    "low":    (5.0, 0.35, 12.0, 25.0),
    "normal": (3.0, 0.15, 8.0, 15.0),
    "high":   (2.0, 0.06, 5.0, 9.0),
}

BED_CLASSES = {57, 59}        # COCO couch, bed
FALL_WINDOW_S = 5.0           # standing to lying within this time = a fall
FALL_ALERT_S = 8.0            # after a fall, alert when still down this long


def _small(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    return cv2.resize(frame, (W, max(2, int(round(h * W / w)))), interpolation=cv2.INTER_AREA)


def _inside(box, boxes, k: float, min_share: float = 0.5) -> bool:
    """True when most of `box` (small-picture pixels) lies inside one of `boxes` (full-picture pixels)."""
    x, y, w, h = box
    area = max(1, w * h)
    for b in boxes:
        bx, by, bw, bh = (v * k for v in b[:4])
        ix = max(0.0, min(x + w, bx + bw) - max(x, bx))
        iy = max(0.0, min(y + h, by + bh) - max(y, by))
        if ix * iy / area >= min_share:
            return True
    return False


# ====================================================================== fire
class FireCheck:
    """Flames: glowing orange / yellow / white areas that are new in the view, keep flickering
    and stay in one place. Judged over a few seconds, not from one picture."""

    def __init__(self):
        self.prev_mask: np.ndarray | None = None
        self.prev_gray: np.ndarray | None = None
        self.bg: np.ndarray | None = None          # how the view usually looks (colour, slowly learned)
        self.known: np.ndarray | None = None       # where the usual look has been learned
        self.heat: np.ndarray | None = None        # where flame colours were seen recently
        self.checks: deque = deque(maxlen=80)      # times of every check
        self.hits: deque = deque(maxlen=80)        # (ts, box, flicker, shimmer) of flame-like areas
        self.last_box = None

    @staticmethod
    def flame_masks(small: np.ndarray):
        """(flame-coloured pixels, glowing pixels). Flames are orange-yellow at the edge and so bright
        in the middle that the camera shows white. Dull reds (bricks, cones, clothes) are too dark."""
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        s, v = hsv[..., 1].astype(np.int16), hsv[..., 2].astype(np.int16)
        b, g, r = (small[..., i].astype(np.int16) for i in range(3))
        orange = (r > 200) & (r >= g) & (g > b) & (g * 100 > r * 35) & ((r - b) > 60) & (s > 60)
        glow = v >= 245
        return orange, glow

    @staticmethod
    def flame_mask(small: np.ndarray) -> np.ndarray:
        orange, glow = FireCheck.flame_masks(small)
        m = (orange | glow).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        return cv2.dilate(m, np.ones((3, 3), np.uint8))

    def update(self, small: np.ndarray, ts: float, people, k: float, seconds: float, min_area_pct: float):
        orange, _ = self.flame_masks(small)
        mask = self.flame_mask(small)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        mono = float(np.mean(cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1])) < 14   # black-and-white camera
        prev, prev_gray = self.prev_mask, self.prev_gray
        self.prev_mask, self.prev_gray = mask, gray
        if self.bg is None or self.bg.shape != small.shape:
            self.bg = small.astype(np.float32)
            self.heat = np.zeros(mask.shape, np.float32)
            self.known = np.ones(mask.shape, bool)   # lamps and signs already glowing are part of the usual view
            return None
        self.heat = np.maximum(self.heat * 0.9, cv2.dilate(mask, np.ones((7, 7), np.uint8)).astype(np.float32) / 255)
        if prev is None or prev.shape != mask.shape:
            return None
        self.checks.append(ts)
        total = mask.shape[0] * mask.shape[1]
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        best = None
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < total * min_area_pct / 100 or area > total * 0.6:
                continue
            box = (int(x), int(y), int(w), int(h))
            if people and _inside(box, people, k):
                continue                          # clothes of a person, not a flame
            roi = labels[y:y + h, x:x + w] == i
            # flame colours at the edge (colour cameras)
            if not mono and float(orange[y:y + h, x:x + w][roi].mean()) < 0.08:
                continue                          # white only: a lamp, a window, the sky
            # new: not part of how this view usually looks (a lamp, a sign, a painted wall)
            known = self.known[y:y + h, x:x + w][roi]
            if known.mean() > 0.5:
                diff = np.abs(small[y:y + h, x:x + w][roi][known].astype(np.float32)
                              - self.bg[y:y + h, x:x + w][roi][known]).max(axis=-1)
                if float(np.mean(diff)) < 18:
                    continue
            both = np.logical_or(roi, prev[y:y + h, x:x + w] > 0)
            changed = np.logical_xor(mask[y:y + h, x:x + w] > 0, prev[y:y + h, x:x + w] > 0) & both
            flicker = float(changed.sum()) / max(1, both.sum())
            shimmer = float(np.mean(cv2.absdiff(gray[y:y + h, x:x + w], prev_gray[y:y + h, x:x + w])[roi]))
            if best is None or area > best[1]:
                best = (box, area, flicker, shimmer)
        # learn the usual view slowly, but never where flame colours were seen recently
        still = self.heat < 0.05
        self.bg[still] = self.bg[still] * 0.97 + small[still].astype(np.float32) * 0.03
        self.known |= still
        if best:
            self.hits.append((ts, best[0], best[2], best[3]))
        # fire = a flame-like area in the same place for `seconds`, in most of the checks, that flickers
        window = [t for t in self.checks if ts - t <= seconds]
        recent = [h for h in self.hits if ts - h[0] <= seconds]
        if not best or len(window) < 3 or ts - window[0] < seconds * 0.8 or len(recent) < 0.7 * len(window):
            return None
        # a fire grows and rises but stays where it started; a car or a person goes somewhere else
        bx, by, bw, bh = best[0]
        gx, gy = bw * 0.25 + 4, bh * 0.25 + 4
        overlaps = sum(1 for _, b, _, _ in recent
                       if b[0] < bx + bw + gx and b[0] + b[2] > bx - gx and b[1] < by + bh + gy and b[1] + b[3] > by - gy)
        first = recent[0][1]
        if overlaps < 0.8 * len(recent) or not (first[0] < bx + bw + gx and first[0] + first[2] > bx - gx):
            return None
        flicker = float(np.mean([h[2] for h in recent]))
        shimmer = float(np.mean([h[3] for h in recent]))
        if flicker < 0.1 or shimmer < 5:
            return None                           # steady: a lamp or an orange object, not a flame
        self.last_box = best[0]
        return best[0]


# ====================================================================== smoke
class SmokeCheck:
    def __init__(self):
        self.bg: np.ndarray | None = None          # usual look: per square [brightness, detail, colour]
        self.learned = 0
        self.since: float | None = None
        self.prev_frac = 0.0

    @staticmethod
    def cells(small: np.ndarray) -> np.ndarray:
        gx, gy = GRID
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        sat = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1]
        detail = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
        size = (gx, gy)
        return np.stack([cv2.resize(gray.astype(np.float32), size, interpolation=cv2.INTER_AREA),
                         cv2.resize(detail, size, interpolation=cv2.INTER_AREA),
                         cv2.resize(sat.astype(np.float32), size, interpolation=cv2.INTER_AREA)], axis=-1)

    def update(self, small: np.ndarray, ts: float, people, k: float, seconds: float, min_cover_pct: float):
        cur = self.cells(small)
        if self.bg is None or self.bg.shape != cur.shape:
            self.bg, self.learned, self.since = cur.copy(), 1, None
            return None
        bg = self.bg
        textured = bg[..., 1] > 3.5
        hazy = (textured & (cur[..., 1] < bg[..., 1] * 0.55)
                & (cur[..., 2] < 60) & (cur[..., 2] <= bg[..., 2] + 8)
                & (cur[..., 0] > 25) & (cur[..., 0] > bg[..., 0] - 50))
        if people:                                  # squares covered by a person are not haze
            gx, gy = GRID
            ch, cw = small.shape[0] / gy, small.shape[1] / gx
            for b in people:
                x0, y0 = int(b[0] * k / cw), int(b[1] * k / ch)
                x1, y1 = int((b[0] + b[2]) * k / cw) + 1, int((b[1] + b[3]) * k / ch) + 1
                hazy[max(0, y0):y1, max(0, x0):x1] = False
        n_tex = int(textured.sum())
        frac = float(hazy.sum()) / max(1, n_tex) * 100
        # the whole view changed at once (lights off, night mode, camera moved): learn it again
        changed = float(np.mean(np.abs(cur[..., 0] - bg[..., 0]) > 35)) * 100
        if changed > 80 and frac < 60 or (frac > 85 and self.prev_frac < 20):
            self.bg, self.since, self.prev_frac = cur.copy(), None, 0.0
            return None
        self.prev_frac = frac
        alarm = None
        if n_tex >= 12 and frac >= min_cover_pct:
            self.since = self.since or ts
            if ts - self.since >= seconds:
                ys, xs = np.nonzero(hazy)
                gx, gy = GRID
                cw, ch = small.shape[1] / gx, small.shape[0] / gy
                alarm = (int(xs.min() * cw), int(ys.min() * ch), int((xs.max() - xs.min() + 1) * cw), int((ys.max() - ys.min() + 1) * ch))
        else:
            self.since = None
        # learn the usual look slowly, never from hazy squares
        rate = 0.2 if self.learned < 10 else 0.01
        keep = hazy[..., None]
        self.bg = np.where(keep, bg, bg * (1 - rate) + cur * rate)
        self.learned += 1
        return alarm


# ====================================================================== person down
class DownCheck:
    def __init__(self):
        self.state: dict[int, dict] = {}            # track id -> {down_since, up_at, alerted}

    @staticmethod
    def posture(box, pose_tilt: float | None, speed: float) -> str:
        """"down", "up" or "unclear" for one picture of one person."""
        x, y, w, h = box[:4]
        aspect = w / max(1, h)
        if speed > 1.0:
            return "up"                             # walking or running
        if pose_tilt is not None:
            if pose_tilt > 0.55:                    # body leans more than ~50 degrees from upright
                return "down"
            if pose_tilt < 0.35:
                return "up"
            return "unclear"
        if aspect > 1.3:
            return "down"
        if aspect < 0.75:
            return "up"
        return "unclear"                            # sitting, bending, half hidden

    def update(self, tracks, ts: float, tilt_of, beds: list, seconds: float):
        """Returns (track, seconds down, fell) for each person who has been down too long.
        One unclear picture does not restart the count; standing up does."""
        out = []
        for t in tracks:
            if t.last_seen != ts:
                continue
            st = self.state.setdefault(t.id, {"down_since": None, "up_at": None, "alerted": False, "fell": False})
            box = t.box
            if any(_overlap(box, b) > 0.4 for b in beds):
                st["down_since"] = None
                continue
            p = self.posture(box, tilt_of(t), t.speed())
            if p == "up":
                st["up_at"], st["down_since"], st["alerted"] = ts, None, False
                continue
            if p == "unclear" and st["down_since"] is None:
                continue
            if st["down_since"] is None:
                st["down_since"] = ts
                st["fell"] = st["up_at"] is not None and ts - st["up_at"] <= FALL_WINDOW_S
            down = ts - st["down_since"]
            need = min(seconds, FALL_ALERT_S) if st["fell"] else seconds
            if down >= need and not st["alerted"]:
                st["alerted"] = True
                out.append((t, down, st["fell"]))
        live = {t.id for t in tracks}
        for tid in list(self.state):
            if tid not in live:
                self.state.pop(tid, None)
        return out


def _overlap(a, b) -> float:
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy / max(1, aw * ah)


# ====================================================================== per camera
class EmergencyMonitor:
    """One per camera. `analyse` returns [(kind, message, box in full-picture pixels)]."""

    def __init__(self):
        self.fire = FireCheck()
        self.smoke = SmokeCheck()
        self.down = DownCheck()

    def analyse(self, frame: np.ndarray, ts: float, tracks, people, objects, rules: dict, cam_name: str,
                sensitivity: str = "normal", tilt_of=None, sleeping_place: bool = False):
        events = []
        fire_s, fire_area, smoke_s, smoke_cover = SENSITIVITY.get(sensitivity, SENSITIVITY["normal"])
        if rules.get("fire", True) or rules.get("smoke", True):
            small = _small(frame)
            k = small.shape[1] / frame.shape[1]
            if rules.get("fire", True):
                box = self.fire.update(small, ts, people, k, fire_s, fire_area)
                if box:
                    events.append(("fire", f"Possible FIRE at {cam_name}. Check the camera now and call for help.", _scale(box, k)))
            if rules.get("smoke", True):
                box = self.smoke.update(small, ts, people, k, smoke_s, smoke_cover)
                if box:
                    events.append(("smoke", f"Heavy SMOKE at {cam_name}. Check the camera now: there may be a fire.", _scale(box, k)))
        if rules.get("person_down", True) and tracks is not None and not sleeping_place:
            beds = [o for o in (objects or []) if len(o) > 5 and o[5] in BED_CLASSES]
            secs = float(rules.get("down_seconds") or 20)
            for t, down, fell in self.down.update(tracks, ts, tilt_of or (lambda t: None), beds, secs):
                how = "fell and has been lying" if fell else "has been lying"
                events.append(("person_down",
                               f"PERSON DOWN at {cam_name}: someone {how} on the ground for {int(down)} seconds. They may have fainted or be hurt. Send help.",
                               tuple(int(v) for v in t.box[:4])))
        return events


def _scale(box, k: float) -> tuple:
    return tuple(int(round(v / k)) for v in box)
