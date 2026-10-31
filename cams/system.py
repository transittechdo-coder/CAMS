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
from .emergency import FORGET_SIMILAR, EmergencyMonitor, FireSmokeAI
from .behaviour import BehaviourEngine
from .insights import Insights
from .cameras import OFFLINE_ALERT_SECONDS, CameraWorker, detect_kind
from .config import Paths
from .db import Database
from .face_engine import DETECT_WIDTHS, FaceEngine, Gallery, ModelsMissing, blur_region, box_iou, crop_face, models_present
from .colour import ColourFilter
from .colour import draw_tag as draw_colour_tag
from .geo import TileCache
from .health import Health
from .visitors import Visitors
from .plates import Plates
from .phones import Phones
from .recorder import Recorder

log = logging.getLogger("cams")

UNKNOWN_SAME_PERSON = 0.50     # two unknown face prints this close = same stranger
UNKNOWN_MEMORY_SECONDS = 120
EMERGENCIES = ("fire", "smoke", "person_down", "emergency_test")
# Speed-ups for the face AI
REUSE_PRINT_S = 3.0            # a face that stays in the same place keeps its face print this long
REUSE_IOU = 0.45               # ... if its box overlaps the earlier box this much
STILL_DIFF = 2.5               # average change (0-255) below which a picture counts as "nothing moved"
STILL_RECHECK_S = 5.0          # even when nothing moves, look again this often


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
        self._still: dict[int, np.ndarray] = {}         # tiny copy of the last analysed picture per camera
        self._prints: dict[int, list[dict]] = {}        # recent face prints per camera, reused while a face stays put
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
        self.emergency: dict[int, EmergencyMonitor] = {}
        self._fire_ai = threading.local()
        self.fire_ai_ok = FireSmokeAI.available(paths.models)
        self._wrong: dict[tuple[int, str], np.ndarray] = {}      # (camera, kind) -> pictures of wrong alarms
        self._wrong_lock = threading.Lock()
        self._alarm_at = 0.0
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
        self.colour = ColourFilter(self)
        self.health = Health(self)
        self.visitors = Visitors(self)
        self.plates = Plates(self)
        self.phones = Phones(self)

    # ================================================================ lifecycle
    def start(self) -> None:
        try:
            self.health.on_start()
        except Exception:
            log.exception("Could not check for a power cut")
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
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self.health.on_stop()
        except Exception:
            pass
        self.colour.stop()
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

    def speed_mode(self) -> str:
        """fast | balanced | detailed. "auto" picks fast on PCs with 4 or fewer processor cores."""
        import os

        m = self.setting("speed_mode") or "auto"
        if m not in DETECT_WIDTHS:
            m = "fast" if (os.cpu_count() or 2) <= 4 else "balanced"
        return m

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
        v = self.visitors.access_problem(person, self.camera_areas.get(cam_id, []))
        if v:
            return v
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
            "colour": self.colour.active(cam_id),
        }

    def _on_frame(self, worker: CameraWorker, frame: np.ndarray) -> None:
        if self._stop.is_set():
            return
        self._queue_analysis(worker, frame)
        st = worker.state
        try:
            self.recorder.tap(worker.id, st.name, frame, st.overlays, time.time() - st.overlays_at < 2.5,
                              colour=lambda img, want: self.colour.apply(worker.id, img, tag=True, want=want)[0])
        except Exception:
            log.exception("Clip buffer failed on camera %s", worker.id)

    def _queue_analysis(self, worker: CameraWorker, frame: np.ndarray) -> None:
        if not self.models_ok:
            return
        fps = max(0.2, self.fsetting("analysis_fps", 2))
        now = time.time()
        if worker.id in self._pending or now - self._last_analysis.get(worker.id, 0) < 1.0 / fps:
            return
        if self._nothing_moved(worker, frame, now):
            return
        try:
            self._queue.put_nowait((worker, frame.copy(), now))
            self._pending.add(worker.id)
            self._last_analysis[worker.id] = now
        except queue.Full:
            pass

    def _nothing_moved(self, worker: CameraWorker, frame: np.ndarray, now: float) -> bool:
        """True when the picture is the same as last time and nobody was in it: skip the AI.

        Saves most of the work on cameras that look at an empty corridor. A picture is
        still analysed every few seconds, and always while people or faces are in view."""
        tiny = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
        tiny = cv2.cvtColor(tiny, cv2.COLOR_BGR2GRAY) if tiny.ndim == 3 else tiny
        prev = self._still.get(worker.id)
        st = worker.state
        empty = not st.overlays and not getattr(st, "people", None)
        if prev is not None and empty and now - self._last_analysis.get(worker.id, 0) < STILL_RECHECK_S \
                and float(cv2.absdiff(prev, tiny).mean()) < STILL_DIFF:
            self.stats["frames_skipped"] = self.stats.get("frames_skipped", 0) + 1
            return True
        self._still[worker.id] = tiny
        return False

    def _face_prints(self, engine: FaceEngine, cam_id: int, frame: np.ndarray, faces: list, ts: float) -> None:
        """Give every face its face print, reusing the last one for a face that has not moved.

        Working out a face print is the slowest step of recognition; a person standing in
        the same place for a few seconds does not need a new one every time."""
        old = self._prints.get(cam_id, [])
        used: set[int] = set()
        new = []
        for f in faces:
            hit = None
            for i, c in enumerate(old):
                if i not in used and ts - c["at"] < REUSE_PRINT_S and box_iou(c["box"], f.box) >= REUSE_IOU:
                    hit = i
                    break
            if hit is None:
                engine.embed(frame, f)
                new.append({"box": f.box, "emb": f.embedding, "q": f.quality, "at": ts})
            else:
                used.add(hit)
                c = old[hit]
                f.embedding, f.quality = c["emb"], c["q"]
                new.append({**c, "box": f.box})
                self.stats["prints_reused"] = self.stats.get("prints_reused", 0) + 1
        self._prints[cam_id] = new

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
        engine.max_width = DETECT_WIDTHS[self.speed_mode()]
        faces = engine.detect(frame)
        self._face_prints(engine, worker.id, frame, faces, ts)
        rules = self.camera_rules.get(worker.id) or parse_analytics(None)
        detector = getattr(engine, "person_detector", None)
        watch = self.behaviour is not None and self.setting("activity_ai") != "0"
        objects: list = []
        if detector and (rules.get("people", True) or watch or rules.get("person_down", True)
                         or float(rules.get("unattended_minutes") or 0) > 0):
            want_objects = watch or bool(rules.get("person_down", True)) or float(rules.get("unattended_minutes") or 0) > 0
            people, objects = detector.detect_scene(frame, objects=want_objects)
        else:
            people = []
        self.stats["people_detected"] += len(people)
        mon = self.monitors.setdefault(worker.id, ActivityMonitor())
        closed = next((a["closed_hours"] for a in self.camera_areas.get(worker.id, []) if a.get("closed_hours")), "")
        for kind, msg in mon.analyse(frame, ts, people, rules, closed, worker.state.name, objects=objects):
            snap = self._save_frame(frame, faces, marks=[mon.bag_box] if kind == "bag_left" else None)
            self._alert(kind, msg, None, worker.id, None, snap)
        self._check_emergencies(worker, frame, ts, mon, people, objects, rules, faces)
        if rules.get("plates") and self.plates.available:
            self.plates.observe(worker.id, worker.state.name, frame, ts, rules)
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

    # ================================================================ emergencies
    def _check_emergencies(self, worker, frame, ts, mon, people, objects, rules, faces) -> None:
        if not any(rules.get(k, True) for k in EMERGENCIES):
            return
        em = self.emergency.setdefault(worker.id, EmergencyMonitor())
        areas = self.camera_areas.get(worker.id, [])
        sleeping = any((a.get("purpose") or "") == "dormitory" for a in areas)
        field = bool(areas) and all(a.get("kind") == "field" for a in areas)
        tracks = list(mon.tracker.tracks.values()) if people is not None else None
        pose_ok = bool(self.behaviour and self.behaviour.pose_ok)
        try:
            events = em.analyse(frame, ts, tracks, people, objects, rules, worker.state.name,
                                self.setting("emergency_sensitivity") or "normal",
                                tilt_of=lambda t: self._body_tilt(frame, t, ts), sleeping_place=sleeping,
                                ai=self.fire_ai(), pose_ok=pose_ok, field_place=field)
        except Exception:
            log.exception("Emergency check failed on camera %s", worker.id)
            return
        for kind, msg, box in events:
            info = em.last_info.get(kind) or {}
            feat = info.get("feature")
            if feat is not None and self._looks_like_wrong_alarm(worker.id, kind, feat):
                log.info("Emergency %s on camera %s not raised: looks like a picture marked Wrong alarm", kind, worker.id)
                continue
            if not mon._ready(kind, ts):
                continue
            place = ", ".join(a["name"] for a in areas[:1])
            if place:
                msg = msg.replace(f"at {worker.state.name}", f"at {worker.state.name} ({place})", 1)
            snap = self._save_frame(frame, faces, marks=[box])
            aid = self._alert(kind, msg, None, worker.id, None, snap)
            if feat is not None:
                self.db.execute("INSERT INTO emergency_examples(alert_id, camera_id, kind, feature, ai_score, created_at) "
                                "VALUES (?,?,?,?,?,?)", (aid, worker.id, kind, np.asarray(feat, np.float32).tobytes(),
                                                         float(info.get("score", info.get("ai", 0)) or 0), time.time()))

    def fire_ai(self) -> FireSmokeAI | None:
        """The fire / smoke second opinion for this worker thread (None if the model is missing)."""
        if not self.fire_ai_ok:
            return None
        ai = getattr(self._fire_ai, "ai", None)
        if ai is None:
            try:
                ai = self._fire_ai.ai = FireSmokeAI(self.paths.models)
            except Exception as exc:
                log.error("Fire / smoke AI could not load: %s", exc)
                self.fire_ai_ok = False
                return None
        return ai

    # -------------------------------------------------------------- wrong alarms
    def _wrong_pictures(self, cam_id: int, kind: str) -> np.ndarray:
        key = (cam_id, kind)
        with self._wrong_lock:
            m = self._wrong.get(key)
            if m is None:
                rows = self.db.query("SELECT feature FROM emergency_examples WHERE camera_id = ? AND kind = ? AND wrong = 1 "
                                     "ORDER BY id DESC LIMIT 300", (cam_id, kind))
                if rows:
                    m = np.stack([np.frombuffer(r["feature"], np.float32) for r in rows])
                    m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-6)
                else:
                    m = np.zeros((0, 1280), np.float32)
                self._wrong[key] = m
            return m

    def _looks_like_wrong_alarm(self, cam_id: int, kind: str, feat) -> bool:
        m = self._wrong_pictures(cam_id, kind)
        if not len(m):
            return False
        f = np.asarray(feat, np.float32)
        f = f / max(float(np.linalg.norm(f)), 1e-6)
        return float((m @ f).max()) >= FORGET_SIMILAR

    def mark_wrong_alarm(self, alert_id: int) -> bool:
        """The guard says this alarm was wrong: remember it for that camera, and close the alert."""
        row = self.db.one("SELECT camera_id, kind FROM emergency_examples WHERE alert_id = ?", (alert_id,))
        self.db.execute("UPDATE emergency_examples SET wrong = 1 WHERE alert_id = ?", (alert_id,))
        self.db.execute("UPDATE alerts SET acknowledged = 1, wrong = 1 WHERE id = ?", (alert_id,))
        if row:
            with self._wrong_lock:
                self._wrong.pop((row["camera_id"], row["kind"]), None)
        return bool(row)

    def _body_tilt(self, frame, track, ts) -> float | None:
        """How much a person's body leans (0 = upright, 1 = flat), from the body pose AI.
        Only worked out for people whose shape could be lying, at most every 2 seconds."""
        x, y, w, h = track.box[:4]
        if w / max(1, h) < 0.75 or self.behaviour is None:
            return None
        cache = getattr(track, "_tilt", None)
        if cache and ts - cache[0] < 2.0:
            return cache[1]
        tilt = None
        est = self.behaviour.pose()
        if est is not None:
            try:
                p = est.estimate(frame, (x, y, w, max(h, w)))
            except Exception:
                p = None
            if p is not None:
                P = p["world"]
                torso = (P[11] + P[12]) / 2 - (P[23] + P[24]) / 2
                tilt = float(np.degrees(np.arccos(np.clip(abs(torso[1]) / (np.linalg.norm(torso) + 1e-6), 0, 1)))) / 90
        track._tilt = (ts, tilt)
        return tilt

    def sound_alarm(self) -> None:
        """Beep on this PC's speakers (Windows), so people hear it even if the CAMS window is closed."""
        if self.setting("alarm_sound") == "0" or time.time() - self._alarm_at < 20:
            return
        self._alarm_at = time.time()

        def beep():
            try:
                import winsound
            except ImportError:
                return
            try:
                for _ in range(6):
                    winsound.Beep(1200, 350)
                    winsound.Beep(800, 350)
            except Exception:
                pass

        threading.Thread(target=beep, name="alarm", daemon=True).start()

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

    def _alert(self, kind: str, message: str, person_id, camera_id, sighting_id, snapshot: str | None = None) -> int:
        aid = self.db.execute(
            "INSERT INTO alerts(created_at, kind, message, person_id, camera_id, sighting_id, snapshot_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), kind, message, person_id, camera_id, sighting_id, snapshot),
        )
        if kind in EMERGENCIES:
            log.warning("EMERGENCY %s: %s", kind, message)
            self.sound_alarm()
        return aid

    def _save_frame(self, frame: np.ndarray, faces, marks=None) -> str | None:
        """Whole-scene picture for an activity alert, with strangers' faces blurred
        and the place of an emergency marked with a red box."""
        img = frame.copy()
        if self.setting("blur_unknown") == "1":
            for f in faces:
                if f.person_id is None:
                    blur_region(img, f.box)
        for b in marks or []:
            x, y, w, h = (int(v) for v in b[:4])
            t = max(2, img.shape[1] // 300)
            cv2.rectangle(img, (x - 4, y - 4), (x + w + 4, y + h + 4), (0, 0, 255), t)
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
        """The picture people see: smaller, coloured if it is black and white (when asked),
        strangers blurred, name boxes."""
        st = w.state
        h, wd = frame.shape[:2]
        k = 1.0
        if wd > max_width:
            k = max_width / wd
            frame = cv2.resize(frame, (max_width, int(h * k)), interpolation=cv2.INTER_AREA)
        frame, coloured = self.colour.apply(w.id, frame)
        sc = (lambda b: tuple(int(round(v * k)) for v in b)) if k != 1.0 else (lambda b: tuple(int(v) for v in b))
        fresh = time.time() - st.overlays_at < 2.5
        if fresh and annotate:
            for p in getattr(st, "people", []):
                px, py, pw, ph = sc(p[:4])
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (200, 200, 200), 1)
        if fresh:
            blur = self.setting("blur_unknown") == "1"
            for o in st.overlays:
                x, y, bw, bh = sc(o["box"])
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
        if coloured:
            draw_colour_tag(frame)
        return frame

    # ================================================================ maintenance
    def _unlink_snaps(self, rels) -> None:
        for rel in rels:
            if rel:
                try:
                    (self.paths.snapshots / rel).unlink(missing_ok=True)
                except OSError:
                    pass

    def delete_routes(self, before: float) -> int:
        """Forget where people were before this time: sightings, their face pictures and clips.

        Alerts are kept for their own time: an alert that pointed at a deleted sighting
        keeps the sighting's picture."""
        old = "SELECT id FROM sightings WHERE last_seen < ?"
        self.db.execute(
            "UPDATE alerts SET snapshot_path = (SELECT s.snapshot_path FROM sightings s WHERE s.id = alerts.sighting_id) "
            f"WHERE snapshot_path IS NULL AND sighting_id IN ({old})", (before,))
        kept = {r["snapshot_path"] for r in self.db.query("SELECT snapshot_path FROM alerts WHERE snapshot_path IS NOT NULL")}
        self.db.execute(f"UPDATE alerts SET sighting_id = NULL WHERE sighting_id IN ({old})", (before,))
        self._unlink_snaps(r["snapshot_path"] for r in self.db.query(
            "SELECT snapshot_path FROM sightings WHERE last_seen < ? AND snapshot_path IS NOT NULL", (before,))
            if r["snapshot_path"] not in kept)
        n = self.db.execute("DELETE FROM sightings WHERE last_seen < ?", (before,))
        try:
            self.recorder.delete_clips(before)
        except Exception:
            log.exception("Clip clean-up failed")
        with self._rec_lock:
            self._active = {k: v for k, v in self._active.items() if v["last_seen"] >= before}
        return n

    def delete_alerts(self, before: float) -> int:
        used = {r["snapshot_path"] for r in self.db.query("SELECT snapshot_path FROM sightings WHERE snapshot_path IS NOT NULL")}
        self._unlink_snaps(r["snapshot_path"] for r in self.db.query(
            "SELECT snapshot_path FROM alerts WHERE created_at < ? AND snapshot_path IS NOT NULL", (before,))
            if r["snapshot_path"] not in used)
        self.db.execute("DELETE FROM emergency_examples WHERE wrong = 0 AND created_at < ?", (before,))
        return self.db.execute("DELETE FROM alerts WHERE created_at < ?", (before,))

    def delete_activity(self, before: float) -> int:
        """Activity timeline, routine results and notes. Pictures used to teach the AI stay."""
        teaching = {r["image_path"] for r in self.db.query(
            "SELECT image_path FROM activity_examples WHERE label IS NOT NULL AND image_path IS NOT NULL")}
        self._unlink_snaps(r["p"] for r in self.db.query(
            "SELECT image_path AS p FROM activity_log WHERE end_ts < ? AND image_path IS NOT NULL", (before,)) if r["p"] not in teaching)
        self._unlink_snaps(r["p"] for r in self.db.query(
            "SELECT image_path AS p FROM activity_examples WHERE ts < ? AND label IS NULL AND image_path IS NOT NULL", (before,)))
        n = self.db.execute("DELETE FROM activity_log WHERE end_ts < ?", (before,))
        self.db.execute("DELETE FROM activity_examples WHERE ts < ? AND label IS NULL", (before,))
        self.db.execute("DELETE FROM person_notes WHERE ts < ?", (before,))
        return n

    def _tidy(self) -> None:
        for d in self.paths.snapshots.glob("*"):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except OSError:
                    pass
        try:
            with self.db.conn() as c:            # give the database's spare log file back to the disk
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

    def purge_old(self) -> int:
        """Automatic clean-up, every 10 minutes. Each kind of data has its own keep time (0 = keep)."""
        now = time.time()
        n = 0
        hours = self.fsetting("route_hours", 12)
        if hours > 0:
            n += self.delete_routes(now - hours * 3600)
        days = self.fsetting("alert_days", 30)
        if days > 0:
            self.delete_alerts(now - days * 86400)
        days = self.fsetting("retention_days", 30)
        if days > 0:
            self.delete_activity(now - days * 86400)
        days = self.fsetting("visitor_days", 30)
        if days > 0:
            self.visitors.purge(now - days * 86400)
        days = self.fsetting("vehicle_days", 30)
        if days > 0:
            self.plates.purge(now - days * 86400)
        try:
            self.recorder.purge()
        except Exception:
            log.exception("Recording clean-up failed")
        try:
            self.tiles.trim(int(self.fsetting("tiles_max_mb", 300) * 1e6))
        except Exception:
            log.exception("Map clean-up failed")
        self._tidy()
        return n

    DATA_KINDS = ("routes", "alerts", "activity", "recordings", "map_cache", "visitors", "vehicles")

    def delete_now(self, kinds) -> dict:
        """The Delete now buttons in Settings."""
        out = {}
        later = time.time() + 60
        if "routes" in kinds:
            out["routes"] = self.delete_routes(later)
        if "alerts" in kinds:
            out["alerts"] = self.delete_alerts(later)
        if "activity" in kinds:
            out["activity"] = self.delete_activity(later)
        if "recordings" in kinds:
            out["recordings"] = self.recorder.delete_recordings()
        if "visitors" in kinds:
            out["visitors"] = self.visitors.purge(later)
        if "vehicles" in kinds and getattr(self, "plates", None):
            out["vehicles"] = self.plates.purge(later)
        if "map_cache" in kinds:
            self.tiles.clear()
            out["map_cache"] = 1
        self._tidy()
        try:
            with self.db.conn() as c:            # shrink the database file
                c.execute("VACUUM")
        except Exception:
            log.exception("Could not shrink the database")
        return out

    def data_usage(self) -> dict:
        """Disk space used by each kind of data, in bytes."""
        import shutil

        def folder(p: Path) -> int:
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0

        db = self.db
        clips = (db.one("SELECT COALESCE(SUM(size_bytes),0) AS n FROM recordings WHERE kind = 'clip'") or {"n": 0})["n"]
        recs = (db.one("SELECT COALESCE(SUM(size_bytes),0) AS n FROM recordings WHERE kind != 'clip'") or {"n": 0})["n"]
        dbf = sum(f.stat().st_size for f in self.paths.data.glob("cams.db*") if f.is_file())
        try:
            du = shutil.disk_usage(self.paths.data)
            free, disk = du.free, du.total
        except OSError:
            free = disk = 0
        count = lambda sql: (db.one(sql) or {"n": 0})["n"]
        return {
            "routes": {"bytes": folder(self.paths.snapshots) + clips, "count": count("SELECT COUNT(*) AS n FROM sightings")},
            "alerts": {"bytes": 0, "count": count("SELECT COUNT(*) AS n FROM alerts")},
            "activity": {"bytes": 0, "count": count("SELECT COUNT(*) AS n FROM activity_log")},
            "recordings": {"bytes": recs, "count": count("SELECT COUNT(*) AS n FROM recordings WHERE kind != 'clip'")},
            "map_cache": {"bytes": self.tiles.size_bytes(), "count": 0},
            "visitors": {"bytes": 0, "count": count("SELECT COUNT(*) AS n FROM visits")},
            "vehicles": {"bytes": 0, "count": count("SELECT COUNT(*) AS n FROM vehicle_log")},
            "database": {"bytes": dbf},
            "people": {"bytes": folder(self.paths.enrollments), "count": count("SELECT COUNT(*) AS n FROM people")},
            "disk_free": free, "disk_total": disk,
        }

    def _maintenance_loop(self) -> None:
        last_purge = time.time() - 540           # first clean-up a minute after start
        last_routines = 0.0
        while not self._stop.wait(10):
            now = time.time()
            try:
                self.health.tick(now)
            except Exception:
                log.exception("Health check failed")
            if now - last_routines >= 55:
                last_routines = now
                try:
                    self.insights.run_due()
                except Exception:
                    log.exception("Routine check failed")
                try:
                    self.visitors.check_overstays(now)
                except Exception:
                    log.exception("Visitor check failed")
            for w in list(self.cameras.values()):
                st = w.state
                if st.status == "offline" and st.offline_since and not st.offline_alerted \
                        and now - st.offline_since > OFFLINE_ALERT_SECONDS:
                    st.offline_alerted = True
                    self._alert("camera_offline", f"Camera {st.name} is offline", None, st.id, None)
            if now - last_purge > 600:
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
