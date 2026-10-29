"""The running CAMS system: cameras + recognition workers + sighting log.

Data flow
---------
camera thread --(newest frame, throttled to analysis_fps)--> queue
recognition worker --detect + face print + match--> overlays + sightings + alerts

The queue is small on purpose: if the PC is too slow for all cameras, old
frames are dropped instead of piling up, so what you see stays "live".
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

import json

from .activity import ActivityMonitor, PersonDetector, in_hours, parse_analytics
from .behaviour import BehaviourEngine
from .insights import Insights
from .cameras import OFFLINE_ALERT_SECONDS, CameraWorker, detect_kind
from .config import Paths
from .db import Database
from .face_engine import FaceEngine, Gallery, ModelsMissing, blur_region, crop_face, models_present
from .geo import TileCache
from .recorder import Recorder

log = logging.getLogger("cams")

UNKNOWN_SAME_PERSON = 0.50     # two unknown face prints this close = same stranger
UNKNOWN_MEMORY_SECONDS = 120


class CamsSystem:
    def __init__(self, paths: Paths, *, start_cameras: bool = True):
        self.paths = paths
        paths.ensure()
        self.db = Database(paths.db_file)
        self.gallery = Gallery()
        self.models_ok = models_present(paths.models)
        self.names: dict[int, dict] = {}
        self.cameras: dict[int, CameraWorker] = {}
        self._cam_lock = threading.RLock()
        self._queue: queue.Queue = queue.Queue(maxsize=8)
        self._pending: set[int] = set()
        self._last_analysis: dict[int, float] = {}
        self._active: dict[tuple, dict] = {}            # open sightings
        self._unknown: dict[int, list[dict]] = {}       # per camera recent strangers
        self._rec_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._settings: dict[str, str] = {}
        self._settings_at = 0.0
        self._api_engine: FaceEngine | None = None
        self._api_lock = threading.Lock()
        self.stats = {"frames_analysed": 0, "faces_seen": 0, "people_detected": 0, "started_at": time.time()}
        self.activity_ok = PersonDetector.available(paths.models)
        self.monitors: dict[int, ActivityMonitor] = {}
        self.camera_areas: dict[int, list[dict]] = {}
        self.camera_rules: dict[int, dict] = {}
        self.reload_gallery()
        self._start_cameras = start_cameras
        # activity AI: timelines of what each recognised person is doing
        self.behaviour = BehaviourEngine(self.db, paths, paths.models) if self.activity_ok else None
        self.insights = Insights(self)
        # video: recordings, sighting clips and exports; satellite tiles for the map
        self.recorder = Recorder(self)
        self.tiles = TileCache(paths.tiles)

    # ================================================================ lifecycle
    def start(self) -> None:
        if self.models_ok:
            n = self.worker_count()
            for i in range(n):
                t = threading.Thread(target=self._recognition_loop, name=f"recog-{i}", daemon=True)
                t.start()
                self._threads.append(t)
        else:
            log.warning("Face models missing in %s - recognition disabled", self.paths.models)
        t = threading.Thread(target=self._maintenance_loop, name="maintenance", daemon=True)
        t.start()
        self._threads.append(t)
        self.refresh_areas()
        if self._start_cameras:
            for cam in self.db.query("SELECT * FROM cameras WHERE enabled = 1"):
                self.start_camera(cam)
            self.recorder.sync_continuous()

    def stop(self) -> None:
        self._stop.set()
        self.recorder.stop_all()
        try:
            self.recorder.flush_clips()
        except Exception:
            log.exception("Could not save the last clips")
        with self._cam_lock:
            for w in list(self.cameras.values()):
                w.stop()
            self.cameras.clear()

    def worker_count(self) -> int:
        import os

        configured = int(self.setting("workers") or 0)
        if configured > 0:
            return configured
        return max(1, min(4, (os.cpu_count() or 2) - 1))

    # ================================================================ settings
    def setting(self, key: str) -> str:
        now = time.time()
        if now - self._settings_at > 3:
            self._settings = self.db.settings()
            self._settings_at = now
        return self._settings.get(key, "")

    def invalidate_settings(self) -> None:
        self._settings_at = 0

    def fsetting(self, key: str, default: float) -> float:
        try:
            return float(self.setting(key))
        except (TypeError, ValueError):
            return default

    # ================================================================ gallery
    def reload_gallery(self) -> None:
        ids, mat = self.db.load_gallery()
        self.gallery.load(ids, mat)
        self.names = {
            r["id"]: r
            for r in self.db.query(
                "SELECT id, full_name, person_code, category, group_name, alert_on_sight FROM people"
            )
        }

    def api_engine(self) -> FaceEngine:
        if self._api_engine is None:
            if not self.models_ok:
                raise ModelsMissing("Face models are not installed.")
            self._api_engine = FaceEngine(self.paths.models, score_threshold=0.7)
        return self._api_engine

    def analyse_image(self, img: np.ndarray):
        """Detect + embed all faces in one still image (enrolment, photo search)."""
        with self._api_lock:
            return self.api_engine().analyse(img)

    # ================================================================ areas and rules
    def refresh_areas(self) -> None:
        """Work out which buildings/zones (with their access rules) each camera watches."""
        areas = []
        for b in self.db.query("SELECT * FROM buildings"):
            b = dict(b)
            for k in ("polygon", "access_categories", "access_groups", "access_people", "floor_names"):
                try:
                    b[k] = json.loads(b.get(k) or "[]")
                except ValueError:
                    b[k] = []
            areas.append(b)
        cam_areas, cam_rules = {}, {}
        for c in self.db.query("SELECT * FROM cameras"):
            found = []
            for a in areas:
                inside = c["building_id"] == a["id"] or (
                    c["map_x"] is not None and a["kind"] != "building"
                    and point_in_polygon(c["map_x"], c["map_y"], a["polygon"]))
                if inside:
                    found.append(a)
            cam_areas[c["id"]] = found
            cam_rules[c["id"]] = parse_analytics(c.get("analytics"))
        self.camera_areas, self.camera_rules = cam_areas, cam_rules

    def access_problem(self, cam_id: int, person: dict | None, now=None) -> str | None:
        """Explain why this person should not be here right now, or None if allowed."""
        for a in self.camera_areas.get(cam_id, []):
            mode = a.get("access_mode") or "everyone"
            listed = bool(person) and (
                person.get("category") in a["access_categories"]
                or (person.get("group_name") or "") in a["access_groups"]
                or person.get("id") in a["access_people"])
            closed = in_hours(a.get("closed_hours") or "", now)
            who = person["full_name"] if person else "Unknown person"
            if mode == "allow" and not listed:
                return f"{who} is in {a['name']}, which is restricted"
            if mode == "deny" and listed:
                return f"{who} is in {a['name']}, where they are not allowed"
            if closed and not (mode == "allow" and listed):
                return f"{who} is in {a['name']} during closed hours ({a['closed_hours']})"
        return None

    # ================================================================ cameras
    def start_camera(self, cam: dict) -> None:
        with self._cam_lock:
            self.stop_camera(cam["id"])
            cam = dict(cam)
            cam["kind"] = cam.get("kind") or detect_kind(cam["source"])
            w = CameraWorker(cam, on_frame=self._on_frame)
            self.cameras[cam["id"]] = w
            w.start()

    def stop_camera(self, cam_id: int) -> None:
        with self._cam_lock:
            w = self.cameras.pop(cam_id, None)
        if w:
            w.stop()

    def restart_camera(self, cam_id: int) -> None:
        cam = self.db.one("SELECT * FROM cameras WHERE id = ?", (cam_id,))
        if not cam:
            self.stop_camera(cam_id)
            return
        if cam["enabled"]:
            self.start_camera(cam)
        else:
            self.stop_camera(cam_id)

    def camera_status(self, cam_id: int) -> dict:
        w = self.cameras.get(cam_id)
        if not w:
            return {"status": "stopped", "fps": 0, "error": ""}
        s = w.state
        return {
            "status": s.status, "fps": s.fps, "error": s.error,
            "width": s.width, "height": s.height,
            "faces": len(s.overlays) if time.time() - s.overlays_at < 3 else 0,
        }

    def _on_frame(self, worker: CameraWorker, frame: np.ndarray) -> None:
        if self._stop.is_set():
            return
        self._queue_analysis(worker, frame)
        st = worker.state
        try:
            self.recorder.tap(worker.id, st.name, frame, st.overlays, time.time() - st.overlays_at < 2.5)
        except Exception:
            log.exception("Clip buffer failed on camera %s", worker.id)

    def _queue_analysis(self, worker: CameraWorker, frame: np.ndarray) -> None:
        if not self.models_ok:
            return
        fps = max(0.2, self.fsetting("analysis_fps", 2))
        now = time.time()
        if worker.id in self._pending or now - self._last_analysis.get(worker.id, 0) < 1.0 / fps:
            return
        try:
            self._queue.put_nowait((worker, frame.copy(), now))
            self._pending.add(worker.id)
            self._last_analysis[worker.id] = now
        except queue.Full:
            pass

    # ================================================================ recognition
    def _recognition_loop(self) -> None:
        try:
            engine = FaceEngine(self.paths.models)
        except Exception as exc:  # pragma: no cover - models checked earlier
            log.error("Cannot start recognition worker: %s", exc)
            return
        detector = None
        if self.activity_ok:
            try:
                detector = PersonDetector(self.paths.models)
            except Exception as exc:
                log.warning("Person detector unavailable: %s", exc)
        engine.person_detector = detector
        while not self._stop.is_set():
            try:
                worker, frame, ts = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.process_frame(engine, worker, frame, ts)
            except Exception:
                log.exception("Recognition failed on camera %s", worker.id)
            finally:
                self._pending.discard(worker.id)

    def process_frame(self, engine: FaceEngine, worker: CameraWorker, frame: np.ndarray, ts: float) -> list[dict]:
        threshold = self.fsetting("match_threshold", 0.40)
        faces = engine.analyse(frame)
        rules = self.camera_rules.get(worker.id) or parse_analytics(None)
        detector = getattr(engine, "person_detector", None)
        watch = self.behaviour is not None and self.setting("activity_ai") != "0"
        objects: list = []
        if detector and (rules.get("people", True) or watch):
            people, objects = detector.detect_scene(frame, objects=watch)
        else:
            people = []
        self.stats["people_detected"] += len(people)
        mon = self.monitors.setdefault(worker.id, ActivityMonitor())
        closed = next((a["closed_hours"] for a in self.camera_areas.get(worker.id, []) if a.get("closed_hours")), "")
        for kind, msg in mon.analyse(frame, ts, people, rules, closed, worker.state.name):
            snap = self._save_frame(frame, faces)
            self._alert(kind, msg, None, worker.id, None, snap)
        overlays = []
        for f in faces:
            pid, sim = self.gallery.match(f.embedding, threshold)
            f.person_id, f.similarity = pid, sim
            person = self.names.get(pid) if pid else None
            overlays.append({
                "box": list(f.box),
                "person_id": pid,
                "name": person["full_name"] if person else "Unknown",
                "confidence": round(sim, 3),
                "watch": bool(person and person["alert_on_sight"]),
            })
            self._record(worker, frame, f, ts)
        if watch and people:
            try:
                tracks = [t for t in mon.tracker.tracks.values() if t.last_seen == ts]
                self.behaviour.observe({"id": worker.id, "name": worker.state.name}, frame, ts, tracks, faces, objects,
                                       self.camera_areas.get(worker.id, []), people)
            except Exception:
                log.exception("Activity AI failed on camera %s", worker.id)
        worker.state.overlays = overlays
        worker.state.people = [list(p[:4]) for p in people]
        worker.state.overlays_at = time.time()
        self.stats["frames_analysed"] += 1
        self.stats["faces_seen"] += len(faces)
        return overlays

    # ================================================================ sightings
    def _unknown_key(self, cam_id: int, emb: np.ndarray, ts: float) -> str:
        bucket = [u for u in self._unknown.get(cam_id, []) if ts - u["ts"] < UNKNOWN_MEMORY_SECONDS]
        for u in bucket:
            if float(u["emb"] @ emb) >= UNKNOWN_SAME_PERSON:
                u["ts"], u["emb"] = ts, emb
                self._unknown[cam_id] = bucket
                return u["key"]
        key = uuid.uuid4().hex[:10]
        bucket.append({"key": key, "emb": emb, "ts": ts})
        self._unknown[cam_id] = bucket[-50:]
        return key

    def _record(self, worker: CameraWorker, frame: np.ndarray, face, ts: float) -> None:
        cam_id = worker.id
        known = face.person_id is not None
        person = self.names.get(face.person_id) if known else None
        problem = self.access_problem(cam_id, person)
        if not known and not worker.restricted and not problem:
            return  # strangers are only logged on restricted cameras / rule areas
        merge = self.fsetting("sighting_merge_seconds", 20)
        key = (cam_id, face.person_id) if known else (cam_id, "u:" + self._unknown_key(cam_id, face.embedding, ts))
        with self._rec_lock:
            open_s = self._active.get(key)
            if open_s and ts - open_s["last_seen"] <= merge:
                open_s["last_seen"] = ts
                open_s["hits"] += 1
                open_s["confidence"] = max(open_s["confidence"], face.similarity)
                self.db.execute(
                    "UPDATE sightings SET last_seen = ?, hits = ?, confidence = ? WHERE id = ?",
                    (ts, open_s["hits"], open_s["confidence"], open_s["id"]),
                )
                return
            snap = self._save_snapshot(frame, face, known) if self.setting("save_snapshots") == "1" else None
            sid = self.db.execute(
                "INSERT INTO sightings(person_id, camera_id, camera_name, first_seen, last_seen, confidence, snapshot_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (face.person_id, cam_id, worker.state.name, ts, ts, face.similarity, snap),
            )
            self._active[key] = {"id": sid, "last_seen": ts, "hits": 1, "confidence": face.similarity}
            try:
                self.recorder.request_clip(cam_id, worker.state.name, sid, ts)
            except Exception:
                log.exception("Could not start a sighting clip")
            if len(self._active) > 5000:
                cutoff = ts - merge
                self._active = {k: v for k, v in self._active.items() if v["last_seen"] >= cutoff}
        if problem:
            self._alert("access_violation", f"{problem} (camera {worker.state.name})", face.person_id, cam_id, sid)
        if person and person["alert_on_sight"]:
            self._alert("watchlist", f"{person['full_name']} seen on {worker.state.name}", face.person_id, cam_id, sid)
        elif not known and worker.restricted and not problem:
            self._alert("unknown_restricted", f"Unknown person on restricted camera {worker.state.name}", None, cam_id, sid)

    def _save_snapshot(self, frame: np.ndarray, face, known: bool) -> str | None:
        crop = crop_face(frame, face.box)
        if crop.size == 0:
            return None
        if not known and self.setting("blur_unknown") == "1":
            h, w = crop.shape[:2]
            blur_region(crop, (0, 0, w, h), pad=0)
        day = time.strftime("%Y%m%d", time.localtime())
        folder = self.paths.snapshots / day
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(folder / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return f"{day}/{name}"

    def _alert(self, kind: str, message: str, person_id, camera_id, sighting_id, snapshot: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO alerts(created_at, kind, message, person_id, camera_id, sighting_id, snapshot_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), kind, message, person_id, camera_id, sighting_id, snapshot),
        )

    def _save_frame(self, frame: np.ndarray, faces) -> str | None:
        """Whole-scene picture for an activity alert, with strangers' faces blurred."""
        img = frame.copy()
        if self.setting("blur_unknown") == "1":
            for f in faces:
                if f.person_id is None:
                    blur_region(img, f.box)
        h, w = img.shape[:2]
        if w > 960:
            img = cv2.resize(img, (960, int(h * 960 / w)))
        day = time.strftime("%Y%m%d", time.localtime())
        folder = self.paths.snapshots / day
        folder.mkdir(parents=True, exist_ok=True)
        name = f"scene_{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(folder / name), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return f"{day}/{name}"

    # ================================================================ live view
    def compose_frame(self, cam_id: int, *, max_width: int = 1280, annotate: bool = False):
        """Newest picture of a camera as shown to people (strangers blurred), and its time."""
        w = self.cameras.get(cam_id)
        if not w or w.state.status != "online":
            return None
        frame = w.latest()
        if frame is None:
            return None
        return self._dress(w, frame, max_width, annotate), w.state.last_frame_at

    def render_frame(self, cam_id: int, *, max_width: int = 1280, annotate: bool = True) -> bytes | None:
        w = self.cameras.get(cam_id)
        if not w:
            return None
        frame = w.latest()
        if frame is None:
            return None
        frame = self._dress(w, frame, max_width, annotate)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None

    def _dress(self, w: CameraWorker, frame: np.ndarray, max_width: int, annotate: bool) -> np.ndarray:
        st = w.state
        fresh = time.time() - st.overlays_at < 2.5
        if fresh and annotate:
            for (px, py, pw, ph) in getattr(st, "people", []):
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (200, 200, 200), 1)
        if fresh:
            blur = self.setting("blur_unknown") == "1"
            for o in st.overlays:
                x, y, bw, bh = o["box"]
                if o["person_id"] is None:
                    if blur:
                        blur_region(frame, (x, y, bw, bh))
                    color = (60, 60, 230)
                elif o["watch"]:
                    color = (0, 165, 255)
                else:
                    color = (90, 200, 90)
                if annotate:
                    cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
                    label = o["name"] if o["person_id"] is None else f"{o['name']} {int(o['confidence'] * 100)}%"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
                    cv2.rectangle(frame, (x, max(0, y - th - 8)), (x + tw + 8, y), color, -1)
                    cv2.putText(frame, label, (x + 4, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        h, wd = frame.shape[:2]
        if wd > max_width:
            frame = cv2.resize(frame, (max_width, int(h * max_width / wd)))
        return frame

    # ================================================================ maintenance
    def purge_old(self) -> int:
        days = self.fsetting("retention_days", 30)
        cutoff = time.time() - days * 86400
        old = self.db.query("SELECT snapshot_path FROM sightings WHERE last_seen < ? AND snapshot_path IS NOT NULL", (cutoff,))
        old += self.db.query("SELECT snapshot_path FROM alerts WHERE created_at < ? AND snapshot_path IS NOT NULL", (cutoff,))
        # activity pictures go too, except those the admin used to teach the AI
        teaching = {r["image_path"] for r in self.db.query("SELECT image_path FROM activity_examples WHERE label IS NOT NULL AND image_path IS NOT NULL")}
        old += [r for r in self.db.query("SELECT image_path AS snapshot_path FROM activity_log WHERE end_ts < ? AND image_path IS NOT NULL", (cutoff,))
                if r["snapshot_path"] not in teaching]
        old += self.db.query("SELECT image_path AS snapshot_path FROM activity_examples WHERE ts < ? AND label IS NULL AND image_path IS NOT NULL", (cutoff,))
        for r in old:
            try:
                (self.paths.snapshots / r["snapshot_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        n = self.db.execute("DELETE FROM sightings WHERE last_seen < ?", (cutoff,))
        self.db.execute("DELETE FROM activity_log WHERE end_ts < ?", (cutoff,))
        self.db.execute("DELETE FROM activity_examples WHERE ts < ? AND label IS NULL", (cutoff,))
        self.db.execute("DELETE FROM person_notes WHERE ts < ?", (cutoff,))
        self.db.execute("DELETE FROM alerts WHERE created_at < ?", (cutoff,))
        try:
            self.recorder.purge()
        except Exception:
            log.exception("Recording clean-up failed")
        # remove empty day folders
        for d in self.paths.snapshots.glob("*"):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        return n

    def _maintenance_loop(self) -> None:
        last_purge = 0.0
        last_routines = 0.0
        while not self._stop.wait(10):
            now = time.time()
            if now - last_routines >= 55:
                last_routines = now
                try:
                    self.insights.run_due()
                except Exception:
                    log.exception("Routine check failed")
            for w in list(self.cameras.values()):
                st = w.state
                if st.status == "offline" and st.offline_since and not st.offline_alerted \
                        and now - st.offline_since > OFFLINE_ALERT_SECONDS:
                    st.offline_alerted = True
                    self._alert("camera_offline", f"Camera {st.name} is offline", None, st.id, None)
            if now - last_purge > 3600:
                last_purge = now
                try:
                    self.purge_old()
                except Exception:
                    log.exception("Retention purge failed")


def snapshot_file(paths: Paths, rel: str) -> Path | None:
    p = (paths.snapshots / rel).resolve()
    if paths.snapshots.resolve() not in p.parents or not p.is_file():
        return None
    return p


def point_in_polygon(x: float, y: float, poly: list) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            inside = not inside
    return inside
