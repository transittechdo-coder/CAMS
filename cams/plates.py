"""Number plates at the gate.

Two small AI models, run by OpenCV on this PC (no internet once downloaded):

* a plate finder (YOLOv9-tiny, from the open-image-models project, MIT licence) that
  finds number plates in the picture, and
* a plate reader (CCT-XS v1, from the fast-plate-ocr project, MIT licence) that reads the
  letters and numbers on each plate.

Both come with CAMS (about 10 MB, see scripts/download_models.py) and run offline. They
need OpenCV 5 (OpenCV 4 crashes on the reader), which is what the CAMS installer contains.

For each camera with "Read number plates" on, CAMS reads plates in the pictures it
already checks. The same plate read again on the same camera within two minutes is
the same visit. Every visit goes into the Vehicle log with the time, the camera and a
small picture of the plate. Plates can be added to a list as *known* (staff, buses,
with the owner's name) or *flagged* (alert when seen). Optionally, any plate not on the
known list raises an alert at that camera (for gates where only known cars may enter).

Tanzanian plates are written T 123 ABC (cars), MC 123 ABC (motorcycles) and similar;
CAMS shows them with spaces in that pattern. The reader was trained on plates from
many countries (Latin letters and numbers) and can make mistakes, so similar plates
(one letter different, 0 / O, 1 / I, 8 / B) are matched to the list too.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from .system import CamsSystem

log = logging.getLogger("cams.plates")

DETECTOR_FILE = "plate_detector_yolov9t_384.onnx"
READER_FILE = "plate_reader_cct_xs_v1.onnx"
MODELS = (DETECTOR_FILE, READER_FILE)
DET_SIZE = 384
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
READ_W, READ_H = 128, 64
SAME_VISIT_S = 120
MIN_PLATE_PX = 18             # plates smaller than this (height in pixels) are too small to read

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle_log (
    id          INTEGER PRIMARY KEY,
    plate       TEXT NOT NULL,              -- as read, letters and numbers only (T123ABC)
    camera_id   INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    camera_name TEXT NOT NULL DEFAULT '',
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    reads       INTEGER NOT NULL DEFAULT 1,
    confidence  REAL NOT NULL DEFAULT 0,
    list_id     INTEGER,                    -- matching plates_list row, if any
    image_path  TEXT                        -- small picture of the plate (snapshots folder)
);
CREATE INDEX IF NOT EXISTS idx_vlog_time ON vehicle_log(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_vlog_plate ON vehicle_log(plate, last_seen DESC);

CREATE TABLE IF NOT EXISTS plates_list (
    id         INTEGER PRIMARY KEY,
    plate      TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL DEFAULT 'known' CHECK (kind IN ('known', 'flagged')),
    owner      TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
"""

# characters the reader confuses with each other
LOOKALIKE = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})


def clean(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def pretty(plate: str) -> str:
    """T123ABC -> T 123 ABC, MC123ABC -> MC 123 ABC (Tanzanian style); others unchanged."""
    m = re.fullmatch(r"([A-Z]{1,3})(\d{3})([A-Z]{2,3})", plate)
    if m:
        return " ".join(m.groups())
    m = re.fullmatch(r"([A-Z]{1,3})(\d{2,4})([A-Z]{0,3})", plate)
    if m and m.group(3):
        return " ".join(m.groups())
    return plate


def similar(a: str, b: str) -> bool:
    """Same plate, allowing the reader's usual mistakes (look-alike characters, one wrong letter)."""
    if a == b:
        return True
    fa, fb = a.translate(LOOKALIKE), b.translate(LOOKALIKE)
    if fa == fb:
        return True
    if len(fa) == len(fb) and len(fa) >= 5:
        return sum(x != y for x, y in zip(fa, fb)) <= 1
    return False


def models_present(folder: Path) -> bool:
    return all((Path(folder) / f).is_file() for f in MODELS)


def opencv_ok() -> bool:
    try:
        return int(cv2.__version__.split(".")[0]) >= 5
    except ValueError:
        return False


# ====================================================================== the AI
class PlateReader:
    """Not thread-safe: one per recognition worker."""

    def __init__(self, folder: Path):
        folder = Path(folder)
        self.det = cv2.dnn.readNet(str(folder / DETECTOR_FILE))
        self.ocr = cv2.dnn.readNet(str(folder / READER_FILE))
        self.ocr_names = self.ocr.getUnconnectedOutLayersNames()

    def find(self, frame: np.ndarray, threshold: float = 0.4) -> list[tuple[int, int, int, int, float]]:
        h, w = frame.shape[:2]
        r = min(DET_SIZE / h, DET_SIZE / w)
        nw, nh = int(round(w * r)), int(round(h * r))
        dw, dh = (DET_SIZE - nw) / 2, (DET_SIZE - nh) / 2
        img = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        top, left = int(round(dh - 0.1)), int(round(dw - 0.1))
        img = cv2.copyMakeBorder(img, top, int(round(dh + 0.1)), left, int(round(dw + 0.1)), cv2.BORDER_CONSTANT, value=(114, 114, 114))
        blob = cv2.dnn.blobFromImage(img, 1 / 255.0, (DET_SIZE, DET_SIZE), swapRB=True)
        self.det.setInput(blob)
        pred = np.asarray(self.det.forward()).reshape(-1, 5)          # cx, cy, w, h, score
        pred = pred[pred[:, 4] >= threshold]
        if not len(pred):
            return []
        xywh = np.column_stack((pred[:, 0] - pred[:, 2] / 2, pred[:, 1] - pred[:, 3] / 2, pred[:, 2], pred[:, 3]))
        keep = np.array(cv2.dnn.NMSBoxes(xywh.tolist(), pred[:, 4].tolist(), threshold, 0.5)).reshape(-1)
        boxes = []
        for i in keep[:10]:
            bx, by, bw, bh = xywh[i]
            x0, y0 = max(0, int((bx - dw) / r)), max(0, int((by - dh) / r))
            x1, y1 = min(w, int((bx + bw - dw) / r)), min(h, int((by + bh - dh) / r))
            if x1 - x0 > 8 and y1 - y0 > 4:
                boxes.append((x0, y0, x1 - x0, y1 - y0, float(pred[i, 4])))
        return boxes

    def read(self, crop: np.ndarray) -> tuple[str, float]:
        img = cv2.resize(crop, (READ_W, READ_H), interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)[np.newaxis].astype(np.uint8)
        self.ocr.setInput(img)
        outs = self.ocr.forward(self.ocr_names)
        probs = next(o for o in outs if o.ndim == 3 and o.shape[-1] == len(ALPHABET))[0]
        idx = probs.argmax(axis=1)
        chars = [ALPHABET[i] for i in idx]
        conf = [float(probs[k, i]) for k, i in enumerate(idx) if ALPHABET[i] != "_"]
        text = "".join(c for c in chars if c != "_")
        return text, (float(np.mean(conf)) if conf else 0.0)

    def scan(self, frame: np.ndarray, min_conf: float = 0.6) -> list[dict]:
        found = []
        h, w = frame.shape[:2]
        for x, y, bw, bh, score in self.find(frame):
            if bh < MIN_PLATE_PX * (h / 1080 if h > 1080 else 1):
                continue
            px, py = int(bw * 0.06), int(bh * 0.1)
            crop = frame[max(0, y - py):min(h, y + bh + py), max(0, x - px):min(w, x + bw + px)]
            if crop.size == 0:
                continue
            text, conf = self.read(crop)
            text = clean(text)
            if len(text) < 4 or conf < min_conf or not re.search(r"\d", text):
                continue
            found.append({"plate": text, "confidence": round(conf * score, 3), "box": (x, y, bw, bh), "crop": crop})
        return found


# ====================================================================== the service
class Plates:
    def __init__(self, system: "CamsSystem"):
        self.sys = system
        self.db = system.db
        with self.db.write() as c:
            c.executescript(SCHEMA)
        self.folder = system.paths.user_models
        self.bundled = system.paths.models
        self._local = threading.local()
        self._open: dict[tuple[int, str], dict] = {}     # (camera, plate) -> open visit
        self._lock = threading.Lock()
        self.list: list[dict] = []
        self.reload_list()

    # ------------------------------------------------------------ models
    def model_dir(self) -> Path | None:
        for d in (self.folder, self.bundled):
            if models_present(d):
                return d
        return None

    @property
    def available(self) -> bool:
        return opencv_ok() and self.model_dir() is not None

    def reader(self) -> PlateReader | None:
        if not opencv_ok():
            return None
        r = getattr(self._local, "reader", None)
        if r is None:
            d = self.model_dir()
            if not d:
                return None
            try:
                r = self._local.reader = PlateReader(d)
            except Exception as exc:
                log.error("Plate AI could not load: %s", exc)
                return None
        return r

    # ------------------------------------------------------------ list
    def reload_list(self) -> None:
        self.list = self.db.query("SELECT * FROM plates_list ORDER BY plate")

    def match(self, plate: str) -> dict | None:
        exact = next((r for r in self.list if r["plate"] == plate), None)
        return exact or next((r for r in self.list if similar(r["plate"], plate)), None)

    # ------------------------------------------------------------ cameras
    def observe(self, cam_id: int, cam_name: str, frame: np.ndarray, ts: float, rules: dict) -> list[dict]:
        """Read plates in one picture; log them and raise alerts. Returns what was read."""
        r = self.reader()
        if r is None:
            return []
        try:
            found = r.scan(frame)
        except Exception:
            log.exception("Plate reading failed on camera %s", cam_id)
            return []
        out = []
        for f in found:
            plate = f["plate"]
            with self._lock:
                key = next((k for k in self._open if k[0] == cam_id and ts - self._open[k]["last"] <= SAME_VISIT_S
                            and similar(k[1], plate)), None)
                if key:
                    v = self._open[key]
                    v["last"] = ts
                    v["reads"] += 1
                    better = f["confidence"] > v["conf"]
                    if better:
                        v["conf"] = f["confidence"]
                    self.db.execute("UPDATE vehicle_log SET last_seen = ?, reads = ?, confidence = ?"
                                    + (", plate = ?" if better else "") + " WHERE id = ?",
                                    (ts, v["reads"], v["conf"], *([plate] if better else []), v["id"]))
                    continue
                hit = self.match(plate)
                img = self._save(f["crop"])
                vid = self.db.execute(
                    "INSERT INTO vehicle_log(plate, camera_id, camera_name, first_seen, last_seen, confidence, list_id, image_path) "
                    "VALUES (?,?,?,?,?,?,?,?)", (plate, cam_id, cam_name, ts, ts, f["confidence"], hit and hit["id"], img))
                self._open[(cam_id, plate)] = {"id": vid, "last": ts, "reads": 1, "conf": f["confidence"]}
                if len(self._open) > 500:
                    self._open = {k: v for k, v in self._open.items() if ts - v["last"] <= SAME_VISIT_S}
            out.append({"plate": plate, "id": vid, "list": hit})
            shown = pretty(plate)
            if hit and hit["kind"] == "flagged":
                self.sys._alert("plate_flagged", f"Flagged vehicle {pretty(hit['plate'])} at {cam_name}"
                                + (f" ({hit['owner']})" if hit["owner"] else "") + (f": {hit['note']}" if hit["note"] else ""),
                                None, cam_id, None, img)
            elif not hit and rules.get("plates_alert_unknown"):
                self.sys._alert("plate_unknown", f"Unknown vehicle {shown} at {cam_name}", None, cam_id, None, img)
        return out

    def _save(self, crop: np.ndarray) -> str | None:
        h, w = crop.shape[:2]
        if w > 320:
            crop = cv2.resize(crop, (320, int(h * 320 / w)))
        day = time.strftime("%Y%m%d", time.localtime())
        folder = self.sys.paths.snapshots / day
        folder.mkdir(parents=True, exist_ok=True)
        name = f"plate_{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(folder / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return f"{day}/{name}"

    def purge(self, before: float) -> int:
        old = self.db.query("SELECT image_path FROM vehicle_log WHERE last_seen < ? AND image_path IS NOT NULL", (before,))
        used = {r["snapshot_path"] for r in self.db.query("SELECT snapshot_path FROM alerts WHERE snapshot_path IS NOT NULL")}
        for r in old:
            if r["image_path"] not in used:
                (self.sys.paths.snapshots / r["image_path"]).unlink(missing_ok=True)
        return self.db.execute("DELETE FROM vehicle_log WHERE last_seen < ?", (before,))
