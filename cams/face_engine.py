"""Face detection, recognition and anonymisation.

Uses two small ONNX models from the OpenCV model zoo, run by OpenCV itself
(no GPU or extra AI framework needed, so it works on ordinary school PCs):

* YuNet  - finds faces and 5 landmarks (eyes, nose, mouth corners)
* SFace  - turns an aligned face into a 128-number "face print"

Two face prints of the same person point in nearly the same direction, so we
compare them with cosine similarity (1.0 = identical).

OpenCV's DNN objects are not thread-safe: create one FaceEngine per thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"
MAX_DETECT_WIDTH = 960
MIN_FACE_PX = 28

ANGLES = ("front", "left", "right", "up", "down")


class ModelsMissing(RuntimeError):
    pass


def models_present(models_dir: Path) -> bool:
    return (models_dir / YUNET_FILE).is_file() and (models_dir / SFACE_FILE).is_file()


@dataclass
class Face:
    box: tuple[int, int, int, int]          # x, y, w, h in original frame pixels
    landmarks: np.ndarray                     # (5, 2)
    score: float
    raw: np.ndarray                           # 15-value YuNet row, original scale
    embedding: np.ndarray | None = None
    yaw: float = 0.0
    pitch: float = 0.0
    angle: str = "front"
    quality: float = 0.0
    person_id: int | None = None
    similarity: float = 0.0
    extra: dict = field(default_factory=dict)


class FaceEngine:
    def __init__(self, models_dir: Path, score_threshold: float = 0.8):
        models_dir = Path(models_dir)
        if not models_present(models_dir):
            raise ModelsMissing(
                f"Face models not found in {models_dir}. Run: python scripts/download_models.py"
            )
        self.detector = cv2.FaceDetectorYN.create(
            str(models_dir / YUNET_FILE), "", (320, 320), score_threshold, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(models_dir / SFACE_FILE), "")
        self._size: tuple[int, int] | None = None

    # ---------------------------------------------------------------- detect
    def detect(self, frame: np.ndarray) -> list[Face]:
        if frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        scale = 1.0
        img = frame
        if w > MAX_DETECT_WIDTH:
            scale = MAX_DETECT_WIDTH / w
            img = cv2.resize(frame, (MAX_DETECT_WIDTH, int(round(h * scale))))
        ih, iw = img.shape[:2]
        if self._size != (iw, ih):
            self.detector.setInputSize((iw, ih))
            self._size = (iw, ih)
        _, rows = self.detector.detect(img)
        faces: list[Face] = []
        if rows is None:
            return faces
        for r in rows:
            r = r.astype(np.float32).copy()
            r[:14] /= scale
            x, y, bw, bh = (int(round(v)) for v in r[:4])
            if bw < MIN_FACE_PX or bh < MIN_FACE_PX:
                continue
            lm = r[4:14].reshape(5, 2)
            f = Face(box=(x, y, bw, bh), landmarks=lm, score=float(r[14]), raw=r)
            f.yaw, f.pitch = estimate_pose(lm)
            f.angle = classify_angle(f.yaw, f.pitch)
            faces.append(f)
        return faces

    # ---------------------------------------------------------------- embed
    def align(self, frame: np.ndarray, face: Face) -> np.ndarray:
        return self.recognizer.alignCrop(frame, face.raw)

    def embed(self, frame: np.ndarray, face: Face) -> np.ndarray:
        crop = self.align(frame, face)
        feat = self.recognizer.feature(crop).reshape(-1).astype(np.float32)
        n = float(np.linalg.norm(feat))
        face.embedding = feat / n if n > 0 else feat
        face.quality = face_quality(crop, face)
        return face.embedding

    def analyse(self, frame: np.ndarray) -> list[Face]:
        faces = self.detect(frame)
        for f in faces:
            self.embed(frame, f)
        return faces


# -------------------------------------------------------------------- pose
def estimate_pose(lm: np.ndarray) -> tuple[float, float]:
    """Rough head yaw/pitch from the 5 landmarks, both roughly in [-1, 1].

    Landmark order from YuNet: right eye, left eye, nose, right mouth, left mouth
    (right/left from the *person's* point of view, i.e. image left = their right).
    yaw > 0  : nose shifted to image-right  -> person turned to their left
    pitch > 0: nose low between eyes and mouth -> looking down
    """
    re, le, nose, rm, lm_ = lm
    eye_mid = (re + le) / 2
    mouth_mid = (rm + lm_) / 2
    eye_dist = float(np.linalg.norm(le - re)) or 1.0
    yaw = float((nose[0] - eye_mid[0]) / eye_dist) * 2.0
    span = float(mouth_mid[1] - eye_mid[1]) or 1.0
    pitch = float((nose[1] - eye_mid[1]) / span - 0.55) * 3.0
    return max(-1.0, min(1.0, yaw)), max(-1.0, min(1.0, pitch))


def classify_angle(yaw: float, pitch: float) -> str:
    if abs(yaw) >= abs(pitch):
        if yaw > 0.35:
            return "left"
        if yaw < -0.35:
            return "right"
    else:
        if pitch > 0.35:
            return "down"
        if pitch < -0.35:
            return "up"
    return "front"


def face_quality(crop: np.ndarray, face: Face) -> float:
    """0..1 score combining detector confidence, sharpness and size."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    sharp = min(1.0, cv2.Laplacian(gray, cv2.CV_64F).var() / 300.0)
    size = min(1.0, min(face.box[2], face.box[3]) / 160.0)
    return round(0.4 * face.score + 0.35 * sharp + 0.25 * size, 3)


# -------------------------------------------------------------------- privacy
def blur_region(frame: np.ndarray, box: tuple[int, int, int, int], pad: float = 0.25) -> None:
    """Pixelate a face in place so it cannot be recognised."""
    h, w = frame.shape[:2]
    x, y, bw, bh = box
    px, py = int(bw * pad), int(bh * pad)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(w, x + bw + px), min(h, y + bh + py)
    if x1 <= x0 or y1 <= y0:
        return
    roi = frame[y0:y1, x0:x1]
    small = cv2.resize(roi, (max(1, (x1 - x0) // 14), max(1, (y1 - y0) // 14)), interpolation=cv2.INTER_LINEAR)
    frame[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)


def crop_face(frame: np.ndarray, box: tuple[int, int, int, int], pad: float = 0.35) -> np.ndarray:
    h, w = frame.shape[:2]
    x, y, bw, bh = box
    px, py = int(bw * pad), int(bh * pad)
    return frame[max(0, y - py): min(h, y + bh + py), max(0, x - px): min(w, x + bw + px)].copy()


# -------------------------------------------------------------------- gallery
class Gallery:
    """In-memory copy of every enrolled face print, shared by all workers."""

    def __init__(self):
        self._lock = threading.RLock()
        self.ids = np.zeros((0,), dtype=np.int64)
        self.mat = np.zeros((0, 128), dtype=np.float32)
        self.version = 0

    def load(self, ids: np.ndarray, mat: np.ndarray) -> None:
        with self._lock:
            if len(mat):
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                norms[norms == 0] = 1
                mat = (mat / norms).astype(np.float32)
            self.ids, self.mat = ids, mat
            self.version += 1

    def __len__(self) -> int:
        return len(self.ids)

    def match(self, emb: np.ndarray, threshold: float) -> tuple[int | None, float]:
        """Best matching person, or (None, best_score) if below threshold."""
        with self._lock:
            if not len(self.ids):
                return None, 0.0
            sims = self.mat @ emb.astype(np.float32)
            i = int(np.argmax(sims))
            best = float(sims[i])
            if best < threshold:
                return None, best
            return int(self.ids[i]), best

    def search(self, emb: np.ndarray, top_k: int = 5) -> list[tuple[int, float]]:
        """Best score per person, highest first (used for photo search)."""
        with self._lock:
            if not len(self.ids):
                return []
            sims = self.mat @ emb.astype(np.float32)
            best: dict[int, float] = {}
            for pid, s in zip(self.ids.tolist(), sims.tolist()):
                if s > best.get(pid, -2):
                    best[pid] = s
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
