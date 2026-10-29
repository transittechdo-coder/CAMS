"""Colour for black-and-white CCTV video (night / infrared cameras).

At night most CCTV cameras switch to infrared and send a black-and-white
picture. CAMS can colour that picture live with an AI model (Zhang et al.,
"Colorful Image Colorization", ECCV 2016 - the ONNX version used in OpenCV's
own colorization sample). The model guesses plausible colours from shapes and
textures. **The colours are a guess, not the truth**: never rely on the colour
of clothing or a car seen in AI-coloured video. CAMS writes "AI colour" on such
pictures.

How it stays live on an ordinary PC
-----------------------------------
The model only predicts the colour part of the picture (a and b of Lab
colour) at a small size. CAMS runs it in a background thread every half second
or so per camera that someone is watching or recording, and keeps the latest
colour map. Every live picture then takes its own brightness (L, full size and
sharp) and the latest colour map, which is cheap, so the video stays smooth.

The model file (about 130 MB) is not in the installer. Settings > Video lets
an admin download it once (internet needed) or load it from a USB stick; it is
kept in %APPDATA%\\CAMS\\models.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from .system import CamsSystem

log = logging.getLogger("cams.colour")

MODEL_NAME = "colorizer.onnx"
MODEL_URLS = [
    # given in OpenCV's samples/dnn/colorization.cpp (5.x)
    "https://storage.googleapis.com/ailia-models/colorization/colorizer.onnx",
]
MODEL_MIN_BYTES = 1_000_000
NET_SIZE = 256
WATCH_SECONDS = 6.0          # keep colouring a camera this long after someone last looked at it
MODES = ("off", "auto", "always")


def is_grey(frame: np.ndarray) -> bool:
    """True for a black-and-white picture (infrared night mode), even if the
    camera sends it as a colour stream with a slight tint."""
    small = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
    if small.ndim == 2:
        return True
    b, g, r = small[..., 0], small[..., 1], small[..., 2]
    spread = (np.abs(b - g) + np.abs(g - r) + np.abs(r - b)) / 3.0
    return float(np.percentile(spread, 90)) < 10.0


def enhance_light(frame: np.ndarray) -> np.ndarray:
    """Make a dark night picture clearer: local contrast on the brightness only."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    lab[..., 0] = clahe.apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


class ColourModel:
    """The ONNX colouring network: brightness in, colour (a, b) out."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.net = cv2.dnn.readNetFromONNX(str(self.path))
        self._lock = threading.Lock()

    def predict_ab(self, frame: np.ndarray) -> np.ndarray:
        """Colour map (h, w, 2) in Lab units for a BGR picture."""
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        L = grey.astype(np.float32) * (100.0 / 255.0)
        small = cv2.resize(L, (NET_SIZE, NET_SIZE), interpolation=cv2.INTER_AREA)
        blob = cv2.dnn.blobFromImage(small, 1.0, (NET_SIZE, NET_SIZE), (0,), False, False)
        with self._lock:
            self.net.setInput(blob)
            out = self.net.forward()
        out = np.asarray(out, dtype=np.float32)
        if out.ndim != 4 or out.shape[1] != 2:
            raise ValueError(f"Unexpected colour model output {out.shape}")
        return np.ascontiguousarray(out[0].transpose(1, 2, 0))


def check_model(path: Path) -> str | None:
    """None if the file is a working colour model, else a reason."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 64:
        return "The file is missing or empty."
    try:
        m = ColourModel(p)
        ab = m.predict_ab(np.full((120, 160, 3), 128, np.uint8))
    except Exception as exc:
        return f"This is not a colour model CAMS can use ({str(exc)[:120]})."
    if ab.shape[2] != 2:
        return "This is not a colour model CAMS can use."
    return None


def colourise(frame: np.ndarray, ab: np.ndarray, enhance: bool = True) -> np.ndarray:
    """Join the picture's own sharp brightness with the (small, smooth) colour map."""
    if enhance:
        frame = enhance_light(frame)
    h, w = frame.shape[:2]
    lab = cv2.cvtColor(frame.astype(np.float32) * (1 / 255.0), cv2.COLOR_BGR2Lab)
    ab_big = cv2.resize(ab, (w, h), interpolation=cv2.INTER_LINEAR)
    lab[..., 1:] = ab_big
    out = cv2.cvtColor(lab, cv2.COLOR_Lab2BGR)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def draw_tag(frame: np.ndarray, text: str = "AI colour") -> None:
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x = frame.shape[1] - tw - 16
    cv2.rectangle(frame, (x - 6, 8), (x + tw + 6, 14 + th + 6), (40, 20, 60), -1)
    cv2.putText(frame, text, (x, 14 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 230, 255), 1, cv2.LINE_AA)


class ColourFilter:
    """Per-camera live colouring with a background AI thread."""

    def __init__(self, system: "CamsSystem"):
        self.sys = system
        self.folder: Path = system.paths.user_models
        self.model: ColourModel | None = None
        self.model_error = ""
        self._ab: dict[int, tuple[float, np.ndarray]] = {}
        self._wanted: dict[int, float] = {}
        self._grey: dict[int, tuple[float, bool]] = {}
        self._latest: dict[int, np.ndarray] = {}
        self._modes: dict[int, str] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.download = {"running": False, "done": 0, "total": 0, "error": ""}
        self.stats = {"runs": 0, "ms": 0.0}
        self.load()
        self.refresh_modes()
        self._thread = threading.Thread(target=self._loop, name="colour-ai", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ model
    @property
    def model_path(self) -> Path:
        return self.folder / MODEL_NAME

    def load(self) -> bool:
        p = self.model_path
        if not p.is_file():
            self.model, self.model_error = None, ""
            return False
        try:
            self.model, self.model_error = ColourModel(p), ""
            return True
        except Exception as exc:
            self.model, self.model_error = None, f"The colour AI file could not be loaded: {exc}"
            log.warning(self.model_error)
            return False

    def install(self, src: Path) -> None:
        """Check a downloaded / uploaded file and make it the colour model."""
        err = check_model(src)
        if err:
            Path(src).unlink(missing_ok=True)
            raise ValueError(err)
        self.folder.mkdir(parents=True, exist_ok=True)
        Path(src).replace(self.model_path)
        self.load()
        with self._lock:
            self._ab.clear()

    def start_download(self, fetch=None) -> None:
        if self.download["running"]:
            return
        self.download = {"running": True, "done": 0, "total": 0, "error": ""}
        threading.Thread(target=self._download, args=(fetch,), name="colour-download", daemon=True).start()

    def _download(self, fetch=None) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / (MODEL_NAME + ".part")
        last = ""
        try:
            for url in MODEL_URLS:
                try:
                    if fetch:
                        fetch(url, tmp, self.download)
                    else:
                        self._fetch(url, tmp)
                    if tmp.stat().st_size < MODEL_MIN_BYTES:
                        raise ValueError("download too small")
                    self.install(tmp)
                    self.download.update(running=False, error="")
                    return
                except Exception as exc:
                    last = str(exc)
                    tmp.unlink(missing_ok=True)
            self.download.update(running=False, error="Could not download the colour AI. Check the internet connection, "
                                 "or load the file colorizer.onnx from a USB stick." + (f" ({last[:80]})" if last else ""))
        except Exception as exc:  # pragma: no cover
            self.download.update(running=False, error=str(exc))

    def _fetch(self, url: str, dest: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "CAMS colour AI download"})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            self.download["total"] = int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                self.download["done"] += len(chunk)

    # ------------------------------------------------------------ cameras
    def refresh_modes(self) -> None:
        self._modes = {c["id"]: (c.get("colour_mode") or "off")
                       for c in self.sys.db.query("SELECT id, colour_mode FROM cameras")}

    def mode(self, cam_id: int) -> str:
        return self._modes.get(cam_id, "off")

    def grey_now(self, cam_id: int, frame: np.ndarray) -> bool:
        now = time.time()
        seen = self._grey.get(cam_id)
        if seen and now - seen[0] < 2.0:
            return seen[1]
        g = is_grey(frame)
        self._grey[cam_id] = (now, g)
        return g

    def active(self, cam_id: int) -> bool:
        """Is this camera's picture being coloured right now?"""
        mode = self.mode(cam_id)
        if mode == "off":
            return False
        if mode == "auto":
            seen = self._grey.get(cam_id)
            if not (seen and seen[1]):
                return False
        return True

    def apply(self, cam_id: int, frame: np.ndarray, tag: bool = False, want: bool = True) -> tuple[np.ndarray, bool]:
        """Colour (or just clear up) a picture if this camera asks for it. Returns (picture, coloured).
        want=False uses the latest colour map without asking the AI to keep this camera coloured."""
        mode = self.mode(cam_id)
        if mode == "off":
            return frame, False
        if mode == "auto" and not self.grey_now(cam_id, frame):
            return frame, False
        enhance = self.sys.setting("colour_enhance") != "0"
        if self.model is None:
            return (enhance_light(frame) if enhance else frame), False
        now = time.time()
        if want:
            self._wanted[cam_id] = now
            self._latest[cam_id] = frame
            self._wake.set()
        got = self._ab.get(cam_id)
        if got is None or now - got[0] > 10:
            return (enhance_light(frame) if enhance else frame), False
        out = colourise(frame, got[1], enhance)
        if tag:
            draw_tag(out)
        return out, True

    # ------------------------------------------------------------ background AI
    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.5)
            self._wake.clear()
            if self.model is None:
                continue
            every = max(0.15, self.sys.fsetting("colour_refresh", 0.6))
            now = time.time()
            due = [(self._ab.get(c, (0,))[0], c) for c, t in list(self._wanted.items())
                   if now - t < WATCH_SECONDS and now - self._ab.get(c, (0,))[0] >= every]
            for _, cam_id in sorted(due):
                frame = self._latest.get(cam_id)
                if frame is None:
                    continue
                t0 = time.perf_counter()
                try:
                    ab = self.model.predict_ab(frame)
                except Exception as exc:
                    log.warning("Colour AI failed: %s", exc)
                    self.model_error = f"The colour AI failed: {exc}"
                    self.model = None
                    break
                self._ab[cam_id] = (time.time(), ab)
                self.stats["runs"] += 1
                self.stats["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            for c in [c for c, t in self._wanted.items() if now - t > 60]:
                self._wanted.pop(c, None)
                self._latest.pop(c, None)
                self._ab.pop(c, None)

    def colour_now(self, cam_id: int) -> None:
        """Run the AI once immediately (tests, first picture)."""
        frame = self._latest.get(cam_id)
        if frame is not None and self.model is not None:
            self._ab[cam_id] = (time.time(), self.model.predict_ab(frame))

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def status(self) -> dict:
        return {
            "installed": self.model is not None,
            "error": self.model_error,
            "size_mb": round(self.model_path.stat().st_size / 1e6, 1) if self.model_path.is_file() else 0,
            "download": dict(self.download),
            "last_ms": self.stats["ms"],
            "active": [c for c in self._modes if self.active(c)],
        }
