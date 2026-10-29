"""Video recording: camera recordings, short clips of each sighting, and exports.

* **Recordings.** Press Record on a camera (or set the camera to record all the
  time). A recorder thread takes the camera's newest picture at a steady speed
  (8 pictures a second by default) and writes it to an .mp4 file, so the time
  of every picture in the file is known exactly: start + n / fps. Long
  recordings are cut into parts (10 minutes when recording all the time).
* **Sighting clips.** Each camera keeps the last few seconds of small pictures
  in memory. When a person is seen, CAMS saves a short clip (3 seconds before
  to 5 seconds after) so you can watch the moment on the person's route.
* **Download a part.** Pick a camera and a time span; CAMS cuts that part out
  of the recordings into one video file.

Faces of people who are not enrolled are blurred in recordings and clips when
"Blur the faces of people who are not enrolled" is on, the same as live view.
Files are MPEG-4 (.mp4) and open in Windows Media Player, Films & TV and VLC.
Inside CAMS they are played by sending the pictures to the window one by one.
"""

from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import cv2
import numpy as np

from .face_engine import blur_region

if TYPE_CHECKING:  # pragma: no cover
    from .system import CamsSystem

log = logging.getLogger("cams.recorder")

FOURCC = "mp4v"
EXT = ".mp4"
CLIP_FPS = 5
CLIP_WIDTH = 640
CLIP_BEFORE_S = 3.0
CONTINUOUS_PART_S = 600          # recording all the time: one file per 10 minutes
MANUAL_PART_S = 3600             # a manual recording longer than an hour is cut into hour parts
STALL_S = 6.0                    # no new picture for this long: close the file, wait for the camera
MAX_EXPORT_S = 3 * 3600


def open_writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*FOURCC), float(fps), size)
    if not w.isOpened():
        # last resort: Motion-JPEG in AVI works with every OpenCV build
        w = cv2.VideoWriter(str(path.with_suffix(".avi")), cv2.VideoWriter_fourcc(*"MJPG"), float(fps), size)
    return w


def fit_width(img: np.ndarray, max_w: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= max_w:
        return img
    return cv2.resize(img, (max_w, int(round(h * max_w / w / 2)) * 2), interpolation=cv2.INTER_AREA)


def even(img: np.ndarray) -> np.ndarray:
    """Video encoders want even sizes."""
    h, w = img.shape[:2]
    return img[: h - h % 2, : w - w % 2]


# ====================================================================== recordings
class RecordingThread(threading.Thread):
    def __init__(self, rec: "Recorder", cam_id: int, mode: str, user: str = ""):
        super().__init__(name=f"rec-{cam_id}-{mode}", daemon=True)
        self.rec, self.cam_id, self.mode, self.user = rec, cam_id, mode, user
        self.stop_event = threading.Event()
        self.cut_event = threading.Event()        # finish the current part now (so it can be read)
        self.started_at = time.time()
        self.row_id: int | None = None
        self.cut_done = threading.Event()

    def stop(self, wait: float = 8) -> None:
        self.stop_event.set()
        self.join(wait)

    def cut(self, wait: float = 8) -> None:
        """Close the file being written so it can be played or exported."""
        if not self.is_alive():
            return
        self.cut_done.clear()
        self.cut_event.set()
        self.cut_done.wait(wait)

    def run(self) -> None:
        r = self.rec
        fps = max(1.0, min(r.sys.fsetting("record_fps", 8), 25.0))
        max_w = int(r.sys.fsetting("record_width", 1280))
        part_s = CONTINUOUS_PART_S if self.mode == "continuous" else MANUAL_PART_S
        writer = None
        cur = None                  # dict(row id, start, n, size, path)
        last_new = time.time()
        last_stamp = 0.0
        while not self.stop_event.is_set():
            now = time.time()
            got = r.sys.compose_frame(self.cam_id, max_width=max_w)
            fresh = got is not None and got[1] != last_stamp
            if fresh:
                last_new, last_stamp = now, got[1]
            stalled = now - last_new > STALL_S or got is None
            if writer is not None and (stalled or self.cut_event.is_set()
                                       or now - cur["start"] >= part_s
                                       or (got is not None and even(got[0]).shape[1::-1] != cur["size"])):
                self._close(writer, cur)
                writer, cur = None, None
            if self.cut_event.is_set():
                self.cut_event.clear()
                self.cut_done.set()
            if stalled:
                self.stop_event.wait(0.5)
                continue
            frame = even(got[0])
            if writer is None:
                cur = self._open(frame, fps)
                writer = cur.pop("writer")
            # write enough pictures to stay on time (repeats a picture if the camera is slower)
            due = int((now - cur["start"]) * fps) + 1
            if due - cur["n"] > fps * 2:          # fell far behind (PC too busy): start a new part
                self._close(writer, cur)
                writer, cur = None, None
                continue
            while cur["n"] < due:
                writer.write(frame)
                cur["n"] += 1
            nxt = cur["start"] + cur["n"] / fps
            self.stop_event.wait(max(0.0, nxt - time.time()))
        if writer is not None:
            self._close(writer, cur)
        self.cut_done.set()

    def _open(self, frame: np.ndarray, fps: float) -> dict:
        r = self.rec
        start = time.time()
        cam = r.sys.db.one("SELECT name FROM cameras WHERE id = ?", (self.cam_id,)) or {"name": f"Camera {self.cam_id}"}
        day = time.strftime("%Y%m%d", time.localtime(start))
        rel = f"{self.cam_id}/{day}/{time.strftime('%H%M%S', time.localtime(start))}_{self.mode}_{uuid.uuid4().hex[:6]}{EXT}"
        path = r.folder / rel
        size = (frame.shape[1], frame.shape[0])
        writer = open_writer(path, fps, size)
        if not path.exists() and path.with_suffix(".avi").exists():
            rel, path = str(Path(rel).with_suffix(".avi")).replace("\\", "/"), path.with_suffix(".avi")
        rid = r.sys.db.execute(
            "INSERT INTO recordings(camera_id, camera_name, kind, path, start_ts, end_ts, fps, width, height, "
            "frames, size_bytes, status, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.cam_id, cam["name"], self.mode, rel, start, start, fps, size[0], size[1], 0, 0, "recording", self.user))
        self.row_id = rid
        return {"writer": writer, "id": rid, "start": start, "n": 0, "size": size, "path": path, "fps": fps}

    def _close(self, writer, cur: dict) -> None:
        writer.release()
        db = self.rec.sys.db
        if cur["n"] < 2:
            Path(cur["path"]).unlink(missing_ok=True)
            db.execute("DELETE FROM recordings WHERE id = ?", (cur["id"],))
            return
        size = Path(cur["path"]).stat().st_size if Path(cur["path"]).exists() else 0
        db.execute("UPDATE recordings SET end_ts = ?, frames = ?, size_bytes = ?, status = 'done' WHERE id = ?",
                   (cur["start"] + cur["n"] / cur["fps"], cur["n"], size, cur["id"]))


# ====================================================================== clips
@dataclass
class ClipJob:
    cam_id: int
    cam_name: str
    start: float
    end: float
    frames: list = field(default_factory=list)       # (ts, image)
    sightings: list = field(default_factory=list)


class Recorder:
    def __init__(self, system: "CamsSystem"):
        self.sys = system
        self.folder: Path = system.paths.recordings
        self.folder.mkdir(parents=True, exist_ok=True)
        self.threads: dict[tuple[int, str], RecordingThread] = {}
        self._lock = threading.RLock()
        self._ring: dict[int, deque] = {}
        self._last_tap: dict[int, float] = {}
        self._jobs: dict[int, list[ClipJob]] = {}
        self._jobs_lock = threading.Lock()
        self._writeq: queue.Queue = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._writer_thread = threading.Thread(target=self._clip_writer, name="clip-writer", daemon=True)
        self._writer_thread.start()
        self._recover()

    # ------------------------------------------------------------ lifecycle
    def _recover(self) -> None:
        """Parts left 'recording' by a crash or power cut: keep them if readable."""
        for row in self.sys.db.query("SELECT * FROM recordings WHERE status = 'recording'"):
            p = self.file(row)
            n = 0
            if p:
                cap = cv2.VideoCapture(str(p))
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) if cap.isOpened() else 0
                cap.release()
            if n > 1:
                self.sys.db.execute("UPDATE recordings SET status='done', frames=?, end_ts=start_ts + ?/fps, size_bytes=? WHERE id=?",
                                    (n, n, p.stat().st_size, row["id"]))
            else:
                if p:
                    p.unlink(missing_ok=True)
                self.sys.db.execute("DELETE FROM recordings WHERE id = ?", (row["id"],))

    def stop_all(self) -> None:
        self._stop.set()
        with self._lock:
            threads = list(self.threads.values())
            self.threads.clear()
        for t in threads:
            t.stop()

    def sync_continuous(self) -> None:
        """Start or stop 'record all the time' to match the camera settings."""
        want = {c["id"] for c in self.sys.db.query("SELECT id FROM cameras WHERE enabled = 1 AND record_mode = 'always'")}
        with self._lock:
            for (cid, mode), t in list(self.threads.items()):
                if mode == "continuous" and (cid not in want or not t.is_alive()):
                    self.threads.pop((cid, mode))
                    threading.Thread(target=t.stop, daemon=True).start()
            for cid in want:
                if (cid, "continuous") not in self.threads:
                    self._start(cid, "continuous", "")

    # ------------------------------------------------------------ manual recording
    def _start(self, cam_id: int, mode: str, user: str) -> RecordingThread:
        t = RecordingThread(self, cam_id, mode, user)
        self.threads[(cam_id, mode)] = t
        t.start()
        return t

    def start(self, cam_id: int, user: str = "") -> dict:
        with self._lock:
            t = self.threads.get((cam_id, "manual"))
            if t and t.is_alive():
                return {"recording": True, "since": t.started_at}
            t = self._start(cam_id, "manual", user)
            return {"recording": True, "since": t.started_at}

    def stop(self, cam_id: int) -> dict:
        with self._lock:
            t = self.threads.pop((cam_id, "manual"), None)
        if t:
            t.stop()
        return {"recording": False, "id": t.row_id if t else None}

    def active(self) -> dict[int, dict]:
        out: dict[int, dict] = {}
        with self._lock:
            for (cid, mode), t in self.threads.items():
                if t.is_alive():
                    out.setdefault(cid, {})[mode] = t.started_at
        return out

    def cut_open_parts(self, cam_id: int) -> None:
        with self._lock:
            ts = [t for (cid, _), t in self.threads.items() if cid == cam_id]
        for t in ts:
            t.cut()

    # ------------------------------------------------------------ clips
    def tap(self, cam_id: int, cam_name: str, frame: np.ndarray, overlays: list, overlays_fresh: bool) -> None:
        """Called by the camera thread for every picture. Keeps a few seconds of small pictures."""
        if self.sys.setting("sighting_clips") == "0":
            return
        now = time.time()
        if now - self._last_tap.get(cam_id, 0) < 1.0 / CLIP_FPS:
            return
        self._last_tap[cam_id] = now
        h, w = frame.shape[:2]
        small = even(fit_width(frame, CLIP_WIDTH))
        if np.shares_memory(small, frame):
            small = small.copy()
        if overlays_fresh and self.sys.setting("blur_unknown") == "1":
            k = small.shape[1] / w
            for o in overlays:
                if o.get("person_id") is None:
                    x, y, bw, bh = o["box"]
                    blur_region(small, (int(x * k), int(y * k), max(1, int(bw * k)), max(1, int(bh * k))))
        ring = self._ring.get(cam_id)
        if ring is None:
            ring = self._ring[cam_id] = deque(maxlen=int(CLIP_BEFORE_S * CLIP_FPS) + 1)
        ring.append((now, small))
        with self._jobs_lock:
            jobs = self._jobs.get(cam_id)
            if not jobs:
                return
            keep = []
            for j in jobs:
                j.frames.append((now, small))
                if now >= j.end:
                    try:
                        self._writeq.put_nowait(j)
                    except queue.Full:
                        log.warning("Clip writer is behind; a clip was skipped")
                else:
                    keep.append(j)
            self._jobs[cam_id] = keep

    def request_clip(self, cam_id: int, cam_name: str, sighting_id: int, ts: float) -> None:
        if self.sys.setting("sighting_clips") == "0":
            return
        total = max(3.0, min(self.sys.fsetting("clip_seconds", 8), 30.0))
        end = ts + max(3.0, total - CLIP_BEFORE_S)
        with self._jobs_lock:
            jobs = self._jobs.setdefault(cam_id, [])
            for j in jobs:                       # someone else's clip on this camera covers it: share
                if j.end >= end - 2:
                    j.sightings.append(sighting_id)
                    j.end = max(j.end, end)
                    return
            if len(jobs) >= 3:
                jobs[-1].sightings.append(sighting_id)
                jobs[-1].end = max(jobs[-1].end, end)
                return
            ring = list(self._ring.get(cam_id, []))
            start = ring[0][0] if ring else ts
            jobs.append(ClipJob(cam_id, cam_name, start, end, frames=ring, sightings=[sighting_id]))

    def _clip_writer(self) -> None:
        while not self._stop.is_set():
            try:
                job: ClipJob = self._writeq.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.write_clip(job)
            except Exception:
                log.exception("Could not save a sighting clip")

    def write_clip(self, job: ClipJob) -> int | None:
        frames = job.frames
        if len(frames) < 2:
            return None
        size = (frames[0][1].shape[1], frames[0][1].shape[0])
        day = time.strftime("%Y%m%d", time.localtime(job.start))
        rel = f"clips/{day}/{uuid.uuid4().hex}{EXT}"
        path = self.folder / rel
        w = open_writer(path, CLIP_FPS, size)
        if not path.exists() and path.with_suffix(".avi").exists():
            rel, path = rel[:-4] + ".avi", path.with_suffix(".avi")
        t0 = frames[0][0]
        n = 0
        for i, (ts, img) in enumerate(frames):
            if img.shape[1::-1] != size:
                img = cv2.resize(img, size)
            nxt = frames[i + 1][0] if i + 1 < len(frames) else ts + 1 / CLIP_FPS
            # keep real time: repeat a picture if pictures were missed
            while t0 + n / CLIP_FPS < nxt - 1e-6:
                w.write(img)
                n += 1
        w.release()
        if n < 2:
            path.unlink(missing_ok=True)
            return None
        db = self.sys.db
        rid = db.execute(
            "INSERT INTO recordings(camera_id, camera_name, kind, path, start_ts, end_ts, fps, width, height, frames, "
            "size_bytes, status, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job.cam_id, job.cam_name, "clip", rel, t0, t0 + n / CLIP_FPS, CLIP_FPS, size[0], size[1], n,
             path.stat().st_size, "done", ""))
        for sid in job.sightings:
            db.execute("UPDATE sightings SET clip_id = ? WHERE id = ?", (rid, sid))
        return rid

    def flush_clips(self) -> None:
        """Write every clip that is still collecting pictures (tests, shutdown)."""
        with self._jobs_lock:
            jobs = [j for js in self._jobs.values() for j in js]
            self._jobs.clear()
        for j in jobs:
            self.write_clip(j)

    # ------------------------------------------------------------ files
    def file(self, row: dict) -> Path | None:
        if not row or not row.get("path"):
            return None
        p = (self.folder / row["path"]).resolve()
        if self.folder.resolve() not in p.parents or not p.is_file():
            return None
        return p

    def delete(self, row: dict) -> None:
        p = self.file(row)
        if p:
            p.unlink(missing_ok=True)
        self.sys.db.execute("UPDATE sightings SET clip_id = NULL WHERE clip_id = ?", (row["id"],))
        self.sys.db.execute("DELETE FROM recordings WHERE id = ?", (row["id"],))

    def disk_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.folder.rglob("*") if f.is_file())

    def purge(self) -> int:
        """Delete old recordings and keep the folder under the size limit."""
        db, removed = self.sys.db, 0
        now = time.time()
        rec_days = self.sys.fsetting("recording_days", 7)
        clip_days = self.sys.fsetting("retention_days", 30)
        old = db.query("SELECT * FROM recordings WHERE status = 'done' AND keep = 0 AND "
                       "((kind != 'clip' AND end_ts < ?) OR (kind = 'clip' AND end_ts < ?))",
                       (now - rec_days * 86400, now - clip_days * 86400))
        for r in old:
            self.delete(r)
            removed += 1
        limit = self.sys.fsetting("recording_max_gb", 50) * 1024 ** 3
        total = (db.one("SELECT COALESCE(SUM(size_bytes), 0) AS n FROM recordings") or {"n": 0})["n"]
        if limit > 0 and total > limit:
            for r in db.query("SELECT * FROM recordings WHERE status = 'done' AND keep = 0 "
                              "ORDER BY (kind = 'manual'), start_ts LIMIT 2000"):
                if total <= limit * 0.95:
                    break
                total -= r["size_bytes"] or 0
                self.delete(r)
                removed += 1
        for d in sorted(self.folder.rglob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        return removed

    # ------------------------------------------------------------ playback
    def frame_at(self, row: dict, t: float, max_width: int = 960) -> bytes | None:
        p = self.file(row)
        if not p:
            return None
        cap = cv2.VideoCapture(str(p))
        try:
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or row["frames"] or 0)
            idx = max(0, min(int(t * row["fps"]), max(0, n - 1)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, img = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, img = cap.read()
            if not ok:
                return None
            ok, buf = cv2.imencode(".jpg", fit_width(img, max_width), [cv2.IMWRITE_JPEG_QUALITY, 80])
            return buf.tobytes() if ok else None
        finally:
            cap.release()

    def stream(self, row: dict, start: float = 0, speed: float = 1, max_width: int = 960,
               stamp: bool = True) -> Iterator[bytes]:
        """Motion-JPEG stream of a recording from `start` seconds, at real speed x speed."""
        p = self.file(row)
        if not p:
            return
        cap = cv2.VideoCapture(str(p))
        fps = row["fps"] or CLIP_FPS
        speed = max(0.25, min(speed, 16.0))
        step = max(1, int(np.ceil(fps * speed / 12)))      # at most ~12 pictures a second to the window
        idx = first = max(0, int(start * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        t_wall = time.time()
        shown = 0
        try:
            while True:
                ok, img = cap.read()
                if not ok:
                    break
                if (idx - first) % step == 0:
                    img = fit_width(img, max_width)
                    if stamp:
                        label = time.strftime("%d %b %Y %H:%M:%S", time.localtime(row["start_ts"] + idx / fps))
                        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                        y = img.shape[0] - 10
                        cv2.rectangle(img, (6, y - th - 6), (14 + tw, y + 5), (0, 0, 0), -1)
                        cv2.putText(img, label, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                    okj, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if okj:
                        jpg = buf.tobytes()
                        yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode()
                               + b"\r\n\r\n" + jpg + b"\r\n")
                    shown += 1
                    wait = t_wall + shown * step / (fps * speed) - time.time()
                    if wait > 0:
                        time.sleep(wait)
                idx += 1
        finally:
            cap.release()

    # ------------------------------------------------------------ export
    def export(self, cam_id: int, start: float, end: float, out_dir: Path) -> tuple[Path, dict]:
        """Cut [start, end] of one camera's recordings into a single file."""
        if end <= start:
            raise ValueError("The end time must be after the start time.")
        if end - start > MAX_EXPORT_S:
            raise ValueError("Download at most 3 hours at a time.")
        rows = self.sys.db.query(
            "SELECT * FROM recordings WHERE camera_id = ? AND kind != 'clip' AND (end_ts > ? OR status = 'recording') "
            "AND start_ts < ? ORDER BY start_ts", (cam_id, start, end))
        if any(r["status"] == "recording" for r in rows):
            self.cut_open_parts(cam_id)
            rows = self.sys.db.query(
                "SELECT * FROM recordings WHERE camera_id = ? AND kind != 'clip' AND status = 'done' AND end_ts > ? "
                "AND start_ts < ? ORDER BY start_ts", (cam_id, start, end))
        rows = [r for r in rows if r["status"] == "done" and self.file(r)]
        # the same moment can be in a manual and an all-the-time recording: use each moment once
        if not rows:
            raise LookupError("Nothing was recorded on this camera at that time.")
        out_dir.mkdir(parents=True, exist_ok=True)
        fps = max(r["fps"] for r in rows)
        size = (rows[0]["width"], rows[0]["height"])
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(start))
        out = out_dir / f"{rows[0]['camera_name'] or 'camera'}-{stamp}{EXT}".replace(" ", "_")
        w = open_writer(out, fps, size)
        if not out.exists() and out.with_suffix(".avi").exists():
            out = out.with_suffix(".avi")
        cursor = start
        written = 0
        for r in rows:
            seg_from = max(cursor, r["start_ts"])
            seg_to = min(end, r["end_ts"])
            if seg_to <= seg_from:
                continue
            cap = cv2.VideoCapture(str(self.file(r)))
            rf = r["fps"]
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((seg_from - r["start_ts"]) * rf))
            t = seg_from
            out_t = written / fps
            while t < seg_to:
                ok, img = cap.read()
                if not ok:
                    break
                if img.shape[1::-1] != size:
                    img = cv2.resize(img, size)
                t += 1 / rf
                while (written + 1) / fps <= (t - seg_from) + out_t + 1e-6:
                    w.write(img)
                    written += 1
            cap.release()
            cursor = seg_to
        w.release()
        if written == 0:
            out.unlink(missing_ok=True)
            raise LookupError("Nothing was recorded on this camera at that time.")
        covered = sum(max(0.0, min(end, r["end_ts"]) - max(start, r["start_ts"])) for r in rows)
        return out, {"seconds": round(written / fps, 1), "covered": round(min(covered, end - start), 1),
                     "asked": round(end - start, 1)}

    def coverage(self, cam_id: int, since: float, until: float) -> list[list[float]]:
        rows = self.sys.db.query(
            "SELECT start_ts, CASE WHEN status = 'recording' THEN ? ELSE end_ts END AS end_ts FROM recordings "
            "WHERE camera_id = ? AND kind != 'clip' AND start_ts < ? AND (end_ts > ? OR status = 'recording') "
            "ORDER BY start_ts", (time.time(), cam_id, until, since))
        spans: list[list[float]] = []
        for r in rows:
            a, b = max(r["start_ts"], since), min(r["end_ts"], until)
            if b <= a:
                continue
            if spans and a <= spans[-1][1] + 2:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
        return [[round(a, 1), round(b, 1)] for a, b in spans]


def clear_tmp(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
