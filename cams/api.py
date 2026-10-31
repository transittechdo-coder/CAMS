"""HTTP API used by the CAMS user interface.

Everything runs on this computer (http://127.0.0.1:8765 by default); no data
leaves the local network.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import APP_FULL_NAME, __version__, auth
from .cameras import RTSP_TEMPLATES, detect_kind, mask_source, scan_network, test_source
from .activity import DEFAULT_ANALYTICS, parse_analytics
from .behaviour import BUILTIN, PURPOSES, guess_purpose
from collections import Counter
from datetime import datetime

from .insights import at as day_at, day_bounds, day_str
from .face_engine import ALL_ANGLES, ANGLES, REFERENCE_ANGLES, ModelsMissing
from .system import CamsSystem, snapshot_file
from . import geo
from .recorder import clear_tmp
from .colour import MODES as COLOUR_MODES, MODEL_NAME as COLOUR_MODEL
from starlette.background import BackgroundTask

COOKIE = "cams_session"
MAX_UPLOAD = 15 * 1024 * 1024
DUPLICATE_WARN = 0.55


# ====================================================================== models
class SetupIn(BaseModel):
    site_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=40)
    full_name: str = ""
    password: str


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    full_name: str = ""
    password: str
    role: str = "operator"


class PasswordIn(BaseModel):
    password: str


class PersonIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)
    person_code: str = ""
    category: str = "student"
    group_name: str = ""
    notes: str = ""
    consent_given: bool = False
    consent_by: str = ""
    consent_date: str = ""
    alert_on_sight: bool = False
    active: bool = True


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1)
    kind: str | None = None
    enabled: bool = True
    restricted: bool = False
    building_id: int | None = None
    floor: int = 0
    map_x: float | None = None
    map_y: float | None = None
    direction: float = 0
    fov: float = 90
    analytics: dict | None = None
    record_mode: str = "off"
    colour_mode: str = "off"


class CameraPlaceIn(BaseModel):
    map_x: float | None = None
    map_y: float | None = None
    direction: float | None = None
    fov: float | None = None
    building_id: int | None = None
    floor: int | None = None


class SourceIn(BaseModel):
    source: str
    kind: str | None = None


class ScanIn(BaseModel):
    subnet: str | None = None


class BuildingIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "building"
    polygon: list[list[float]]
    height_m: float = 6
    floors: int = 1
    color: str = "#5b8def"
    rotation: float = 0
    floor_names: list[str] = []
    access_mode: str = "everyone"
    access_categories: list[str] = []
    access_groups: list[str] = []
    access_people: list[int] = []
    closed_hours: str = ""
    purpose: str = ""


class MapIn(BaseModel):
    width_m: float = Field(gt=1, le=20000)
    height_m: float = Field(gt=1, le=20000)


class GeoIn(BaseModel):
    lat: float | None = Field(default=None, gt=-85, lt=85)
    lng: float | None = Field(default=None, ge=-180, le=180)


class SatelliteIn(BaseModel):
    lat: float = Field(gt=-85, lt=85)
    lng: float = Field(ge=-180, le=180)
    width_m: float = Field(ge=10, le=20000)
    height_m: float = Field(ge=10, le=20000)
    keep_buildings: bool = True


class RecordIn(BaseModel):
    action: str = "start"          # start | stop


class RecordingIn(BaseModel):
    keep: bool | None = None
    note: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------- activity AI
TIME_RE = r"^([01]?\d|2[0-3]):[0-5]\d$"


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start: str = Field(pattern=TIME_RE)
    end: str = Field(pattern=TIME_RE)
    days: list[int] = [0, 1, 2, 3, 4]
    area_ids: list[int] = []
    purpose: str = ""
    expect: str = "present"
    who_categories: list[str] = []
    who_groups: list[str] = []
    who_people: list[int] = []
    grace_min: int = Field(default=10, ge=0, le=240)
    alert: bool = False
    enabled: bool = True


class ActivityRuleIn(BaseModel):
    activity: str = Field(min_length=1, max_length=60)
    start: str = Field(pattern=TIME_RE)
    end: str = Field(pattern=TIME_RE)
    days: list[int] = []
    area_ids: list[int] = []
    purpose: str = ""
    body: str = "any"
    enabled: bool = True


class ActivityTypeIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)


class LabelIn(BaseModel):
    label: str | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)


# ====================================================================== helpers
def _decode_image(data: bytes) -> np.ndarray:
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Image is too large (max 15 MB).")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "That file is not a readable image.")
    return img


def _largest(faces):
    return max(faces, key=lambda f: f.box[2] * f.box[3]) if faces else None


def _person_or_404(sysm: CamsSystem, pid: int) -> dict:
    p = sysm.db.one("SELECT * FROM people WHERE id = ?", (pid,))
    if not p:
        raise HTTPException(404, "Person not found.")
    return p


def _camera_public(sysm: CamsSystem, cam: dict) -> dict:
    out = dict(cam)
    out["source_display"] = mask_source(cam["source"])
    out["analytics"] = parse_analytics(cam.get("analytics"))
    out["live"] = sysm.camera_status(cam["id"])
    out["recording"] = sysm.recorder.active().get(cam["id"], {})
    return out


def _last_seen(sysm: CamsSystem, pid: int) -> dict | None:
    row = sysm.db.one(
        "SELECT s.*, c.map_x, c.map_y, c.floor, c.building_id, b.name AS building_name "
        "FROM sightings s LEFT JOIN cameras c ON c.id = s.camera_id "
        "LEFT JOIN buildings b ON b.id = c.building_id "
        "WHERE s.person_id = ? ORDER BY s.last_seen DESC LIMIT 1",
        (pid,),
    )
    if row:
        _add_gps(sysm, [row])
    return row


def _add_gps(sysm: CamsSystem, rows: list[dict]) -> list[dict]:
    """Add the exact latitude / longitude of each row's camera when the map is placed on Earth."""
    g = geo.georef_from_settings(sysm.db.settings())
    for r in rows:
        if g and r.get("map_x") is not None and r.get("map_y") is not None:
            r["lat"], r["lng"] = g.to_latlng(r["map_x"], r["map_y"])
    return rows


def _hours_ok(spec: str) -> bool:
    import re
    return bool(re.fullmatch(r"\s*([01]?\d|2[0-3]):[0-5]\d\s*-\s*([01]?\d|2[0-3]):[0-5]\d\s*", spec or ""))


def _building_out(b: dict) -> dict:
    out = dict(b)
    for k in ("polygon", "floor_names", "access_categories", "access_groups", "access_people"):
        try:
            out[k] = json.loads(b.get(k) or "[]")
        except ValueError:
            out[k] = []
    return out


def create_app(sysm: CamsSystem) -> FastAPI:
    app = FastAPI(title=f"CAMS - {APP_FULL_NAME}", version=__version__, docs_url=None, redoc_url=None)
    db = sysm.db
    paths = sysm.paths

    # ------------------------------------------------------------ auth deps
    def current_user(request: Request) -> dict:
        user = auth.user_for_token(db, request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(401, "Please sign in.")
        return user

    def need(role: str):
        def dep(user: dict = Depends(current_user)) -> dict:
            if not auth.role_at_least(user, role):
                raise HTTPException(403, f"This needs the {role} role.")
            return user
        return dep

    viewer = Depends(need("viewer"))
    operator = Depends(need("operator"))
    admin = Depends(need("admin"))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    # ------------------------------------------------------------ status / setup
    @app.get("/api/status")
    def status(request: Request):
        user = auth.user_for_token(db, request.cookies.get(COOKIE))
        return {
            "app": "CAMS",
            "name": APP_FULL_NAME,
            "version": __version__,
            "needs_setup": not auth.has_users(db),
            "models_ok": sysm.models_ok,
            "activity_ai": {"objects": sysm.behaviour is not None, "pose": bool(sysm.behaviour and sysm.behaviour.pose_ok)},
            "site_name": db.get_setting("site_name"),
            "user": user and {k: user[k] for k in ("id", "username", "full_name", "role")},
            "onboarding_done": db.get_setting("onboarding_done") == "1",
            "map_mouse": db.get_setting("map_mouse") or "standard",
            "ui_loads": sysm.stats.get("ui_loads", 0),
        }

    @app.post("/api/setup")
    def setup(body: SetupIn, response: Response):
        if auth.has_users(db):
            raise HTTPException(409, "CAMS is already set up.")
        err = auth.validate_password(body.password)
        if err:
            raise HTTPException(400, err)
        auth.create_user(db, body.username, body.password, "admin", body.full_name)
        db.set_settings({"site_name": body.site_name.strip()})
        sysm.invalidate_settings()
        token = auth.login(db, body.username, body.password)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=auth.SESSION_SECONDS)
        db.audit(body.username, "setup", {"site": body.site_name})
        return {"ok": True}

    @app.post("/api/login")
    def login(body: LoginIn, response: Response):
        token = auth.login(db, body.username, body.password)
        if not token:
            time.sleep(0.8)  # slow down password guessing
            db.audit(body.username, "login_failed")
            raise HTTPException(401, "Wrong username or password.")
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=auth.SESSION_SECONDS)
        db.audit(body.username, "login")
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        if token:
            auth.logout(db, token)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    # ------------------------------------------------------------ users
    @app.get("/api/users")
    def list_users(user=admin):
        return db.query("SELECT id, username, full_name, role, created_at FROM users ORDER BY username")

    @app.post("/api/users")
    def add_user(body: UserIn, user=admin):
        if body.role not in auth.ROLES:
            raise HTTPException(400, "Role must be admin, operator or viewer.")
        err = auth.validate_password(body.password)
        if err:
            raise HTTPException(400, err)
        if db.one("SELECT id FROM users WHERE username = ?", (body.username,)):
            raise HTTPException(409, "That username is taken.")
        uid = auth.create_user(db, body.username, body.password, body.role, body.full_name)
        db.audit(user["username"], "user_add", {"username": body.username, "role": body.role})
        return {"id": uid}

    @app.put("/api/users/{uid}/password")
    def set_password(uid: int, body: PasswordIn, user=Depends(current_user)):
        if uid != user["id"] and not auth.role_at_least(user, "admin"):
            raise HTTPException(403, "You can only change your own password.")
        err = auth.validate_password(body.password)
        if err:
            raise HTTPException(400, err)
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.password), uid))
        db.execute("DELETE FROM sessions WHERE user_id = ? AND user_id != ?", (uid, user["id"]))
        db.audit(user["username"], "password_change", {"user_id": uid})
        return {"ok": True}

    @app.delete("/api/users/{uid}")
    def delete_user(uid: int, user=admin):
        if uid == user["id"]:
            raise HTTPException(400, "You cannot delete your own account.")
        admins = db.one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND id != ?", (uid,))["n"]
        target = db.one("SELECT * FROM users WHERE id = ?", (uid,))
        if target and target["role"] == "admin" and admins == 0:
            raise HTTPException(400, "Keep at least one admin.")
        db.execute("DELETE FROM users WHERE id = ?", (uid,))
        db.audit(user["username"], "user_delete", {"user_id": uid})
        return {"ok": True}

    # ------------------------------------------------------------ dashboard
    @app.get("/api/dashboard")
    def dashboard(user=viewer):
        day_start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        cams = db.query("SELECT id, name, enabled FROM cameras")
        statuses = [sysm.camera_status(c["id"]) for c in cams if c["enabled"]]
        return {
            "people": db.one("SELECT COUNT(*) AS n FROM people WHERE active = 1")["n"],
            "enrolled": db.one("SELECT COUNT(DISTINCT person_id) AS n FROM face_samples")["n"],
            "cameras": len(cams),
            "cameras_online": sum(1 for s in statuses if s["status"] == "online"),
            "sightings_today": db.one("SELECT COUNT(*) AS n FROM sightings WHERE last_seen >= ?", (day_start,))["n"],
            "people_today": db.one(
                "SELECT COUNT(DISTINCT person_id) AS n FROM sightings WHERE last_seen >= ? AND person_id IS NOT NULL",
                (day_start,),
            )["n"],
            "open_alerts": db.one("SELECT COUNT(*) AS n FROM alerts WHERE acknowledged = 0")["n"],
            "recent": db.query(
                "SELECT s.id, s.person_id, s.camera_name, s.last_seen, s.confidence, s.snapshot_path, "
                "p.full_name, p.group_name FROM sightings s LEFT JOIN people p ON p.id = s.person_id "
                "ORDER BY s.last_seen DESC LIMIT 15"
            ),
            "models_ok": sysm.models_ok,
            "stats": sysm.stats,
        }

    # ------------------------------------------------------------ people
    @app.get("/api/people")
    def list_people(q: str = "", category: str = "", group: str = "", limit: int = 500, user=viewer):
        sql = (
            "SELECT p.*, (SELECT COUNT(*) FROM face_samples f WHERE f.person_id = p.id) AS samples, "
            "(SELECT GROUP_CONCAT(angle) FROM (SELECT angle FROM face_samples WHERE person_id = p.id "
            "UNION SELECT angle FROM reference_photos WHERE person_id = p.id)) AS angles, "
            "(SELECT MAX(last_seen) FROM sightings s WHERE s.person_id = p.id) AS last_seen "
            "FROM people p WHERE 1=1"
        )
        params: list[Any] = []
        if q:
            sql += " AND (p.full_name LIKE ? OR p.person_code LIKE ? OR p.group_name LIKE ?)"
            params += [f"%{q}%"] * 3
        if category:
            sql += " AND p.category = ?"
            params.append(category)
        if group:
            sql += " AND p.group_name = ?"
            params.append(group)
        sql += " ORDER BY p.full_name LIMIT ?"
        params.append(min(max(limit, 1), 5000))
        return db.query(sql, params)

    @app.get("/api/people/groups")
    def groups(user=viewer):
        return [r["group_name"] for r in db.query(
            "SELECT DISTINCT group_name FROM people WHERE group_name != '' ORDER BY group_name")]

    @app.post("/api/people")
    def add_person(body: PersonIn, user=operator):
        pid = db.execute(
            "INSERT INTO people(full_name, person_code, category, group_name, notes, consent_given, consent_by, "
            "consent_date, alert_on_sight, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (body.full_name.strip(), body.person_code.strip(), body.category, body.group_name.strip(), body.notes,
             int(body.consent_given), body.consent_by, body.consent_date, int(body.alert_on_sight),
             int(body.active), time.time()),
        )
        sysm.reload_gallery()
        db.audit(user["username"], "person_add", {"id": pid, "name": body.full_name})
        return {"id": pid}

    @app.get("/api/people/{pid}")
    def get_person(pid: int, user=viewer):
        p = _person_or_404(sysm, pid)
        p["samples"] = db.query(
            "SELECT id, angle, quality, created_at FROM face_samples WHERE person_id = ? ORDER BY created_at", (pid,))
        p["references"] = db.query(
            "SELECT id, angle, created_at FROM reference_photos WHERE person_id = ? ORDER BY created_at", (pid,))
        p["last_seen"] = _last_seen(sysm, pid)
        return p

    @app.put("/api/people/{pid}")
    def update_person(pid: int, body: PersonIn, user=operator):
        _person_or_404(sysm, pid)
        db.execute(
            "UPDATE people SET full_name=?, person_code=?, category=?, group_name=?, notes=?, consent_given=?, "
            "consent_by=?, consent_date=?, alert_on_sight=?, active=? WHERE id=?",
            (body.full_name.strip(), body.person_code.strip(), body.category, body.group_name.strip(), body.notes,
             int(body.consent_given), body.consent_by, body.consent_date, int(body.alert_on_sight),
             int(body.active), pid),
        )
        sysm.reload_gallery()
        db.audit(user["username"], "person_update", {"id": pid})
        return {"ok": True}

    @app.delete("/api/people/{pid}")
    def delete_person(pid: int, user=admin):
        """Right to erasure: removes the person, face prints, photos and sightings."""
        p = _person_or_404(sysm, pid)
        for s in db.query("SELECT snapshot_path FROM sightings WHERE person_id = ? AND snapshot_path IS NOT NULL", (pid,)):
            (paths.snapshots / s["snapshot_path"]).unlink(missing_ok=True)
        for s in db.query("SELECT image_path FROM activity_log WHERE person_id = ? AND image_path IS NOT NULL "
                          "UNION SELECT image_path FROM activity_examples WHERE person_id = ? AND image_path IS NOT NULL", (pid, pid)):
            (paths.snapshots / s["image_path"]).unlink(missing_ok=True)
        shutil.rmtree(paths.enrollments / str(pid), ignore_errors=True)
        for r in db.query("SELECT r.* FROM recordings r WHERE r.kind = 'clip' AND r.id IN "
                          "(SELECT clip_id FROM sightings WHERE person_id = ? AND clip_id IS NOT NULL)", (pid,)):
            sysm.recorder.delete(r)
        db.execute("DELETE FROM people WHERE id = ?", (pid,))
        if sysm.behaviour:
            sysm.behaviour.reload()
        sysm.reload_gallery()
        db.audit(user["username"], "person_delete", {"id": pid, "name": p["full_name"]})
        return {"ok": True}

    @app.post("/api/people/import")
    async def import_people(file: UploadFile = File(...), user=operator):
        raw = (await file.read()).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(raw))
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        if "full_name" not in cols and "name" not in cols:
            raise HTTPException(400, "The CSV needs a full_name column (optional: person_code, category, group_name).")
        added = 0
        for row in reader:
            r = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
            name = r.get("full_name") or r.get("name")
            if not name:
                continue
            cat = r.get("category", "student").lower() or "student"
            if cat not in ("student", "staff", "visitor", "contractor", "other"):
                cat = "other"
            db.execute(
                "INSERT INTO people(full_name, person_code, category, group_name, created_at) VALUES (?,?,?,?,?)",
                (name, r.get("person_code", ""), cat, r.get("group_name", r.get("class", "")), time.time()),
            )
            added += 1
        sysm.reload_gallery()
        db.audit(user["username"], "people_import", {"count": added})
        return {"added": added}

    # ------------------------------------------------------------ enrolment (multi-angle face capture)
    def _save_reference(pid: int, img: np.ndarray, angle: str, user: dict) -> dict:
        folder = paths.enrollments / str(pid)
        folder.mkdir(parents=True, exist_ok=True)
        h, w = img.shape[:2]
        if max(h, w) > 1200:
            s_ = 1200 / max(h, w)
            img = cv2.resize(img, (int(w * s_), int(h * s_)))
        name = f"ref_{angle}_{uuid.uuid4().hex[:8]}.jpg"
        cv2.imwrite(str(folder / name), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        rid = db.execute("INSERT INTO reference_photos(person_id, angle, image_path, created_at) VALUES (?,?,?,?)",
                         (pid, angle, f"{pid}/{name}", time.time()))
        db.audit(user["username"], "reference_photo_add", {"person_id": pid, "angle": angle})
        return {"id": rid, "angle": angle, "reference": True,
                "note": "Saved as a reference picture. The back and top of the head cannot be used to recognise a person."}

    def _enroll_image(pid: int, img: np.ndarray, angle_hint: str | None, user: dict) -> dict:
        if angle_hint in REFERENCE_ANGLES:
            return _save_reference(pid, img, angle_hint, user)
        try:
            faces = sysm.analyse_image(img)
        except ModelsMissing as exc:
            raise HTTPException(503, str(exc))
        if not faces:
            raise HTTPException(422, "No face found. Use a clear, well-lit photo with the face fully visible, or mark the photo as Back or Top.")
        if len(faces) > 1:
            areas = sorted((f.box[2] * f.box[3] for f in faces), reverse=True)
            if areas[1] > areas[0] * 0.5:
                raise HTTPException(422, "More than one face in the picture. Use a photo of only this person.")
        face = _largest(faces)
        warning = None
        for other_id, score in sysm.gallery.search(face.embedding, top_k=3):
            if other_id != pid and score >= DUPLICATE_WARN:
                other = sysm.names.get(other_id, {}).get("full_name", f"#{other_id}")
                warning = f"This face looks very similar to {other} ({int(score * 100)}%). Check it is the right person."
                break
        angle = angle_hint if angle_hint in ANGLES else face.angle
        folder = paths.enrollments / str(pid)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{angle}_{uuid.uuid4().hex[:8]}.jpg"
        crop = sysm.api_engine().align(img, face)
        big = img[max(0, face.box[1] - face.box[3] // 2): face.box[1] + face.box[3] * 3 // 2,
                  max(0, face.box[0] - face.box[2] // 2): face.box[0] + face.box[2] * 3 // 2]
        cv2.imwrite(str(folder / name), big if big.size else crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
        sid = db.add_face_sample(pid, face.embedding, angle, f"{pid}/{name}", face.quality)
        if not db.one("SELECT photo_path FROM people WHERE id = ? AND photo_path IS NOT NULL", (pid,)) or angle == "front":
            db.execute("UPDATE people SET photo_path = ? WHERE id = ?", (f"{pid}/{name}", pid))
        sysm.reload_gallery()
        db.audit(user["username"], "face_enrol", {"person_id": pid, "angle": angle})
        return {
            "id": sid, "angle": angle, "detected_angle": face.angle, "quality": face.quality, "reference": False,
            "yaw": round(face.yaw, 2), "pitch": round(face.pitch, 2), "warning": warning,
        }

    @app.post("/api/people/{pid}/samples")
    async def enroll_upload(pid: int, files: list[UploadFile] = File(...), angle: str = Form(""), user=operator):
        _person_or_404(sysm, pid)
        results, errors = [], []
        for f in files:
            try:
                img = _decode_image(await f.read())
                results.append(_enroll_image(pid, img, angle or None, user))
            except HTTPException as exc:
                errors.append({"file": f.filename, "error": exc.detail})
        if not results and errors:
            raise HTTPException(422, errors[0]["error"])
        return {"added": results, "errors": errors}

    @app.post("/api/people/{pid}/samples/from-camera/{cam_id}")
    def enroll_from_camera(pid: int, cam_id: int, angle: str = "", user=operator):
        _person_or_404(sysm, pid)
        w = sysm.cameras.get(cam_id)
        frame = w.latest() if w else None
        if frame is None:
            raise HTTPException(409, "That camera has no picture right now.")
        return _enroll_image(pid, frame, angle or None, user)

    @app.post("/api/people/{pid}/samples/video")
    async def enroll_video(pid: int, file: UploadFile = File(...), user=operator):
        """360-degree enrolment from a short turn-around video: keeps the best frame per angle."""
        _person_or_404(sysm, pid)
        data = await file.read()
        if len(data) > 200 * 1024 * 1024:
            raise HTTPException(413, "Video is too large (max 200 MB). Record 10-20 seconds.")
        tmp = paths.data / f"upload_{uuid.uuid4().hex}{Path(file.filename or 'v.mp4').suffix[:6]}"
        tmp.write_bytes(data)
        best: dict[str, tuple[float, np.ndarray]] = {}
        no_face: list[tuple[float, int, np.ndarray]] = []
        seen_face_before = False
        frames = 0
        try:
            cap = cv2.VideoCapture(str(tmp))
            if not cap.isOpened():
                raise HTTPException(400, "This video format cannot be read. Use MP4 or AVI.")
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            step = max(1, int(fps / 5))
            idx = 0
            while frames < 600:
                ok, frame = cap.read()
                if not ok:
                    break
                idx += 1
                if idx % step:
                    continue
                frames += 1
                try:
                    faces = sysm.analyse_image(frame)
                except ModelsMissing as exc:
                    raise HTTPException(503, str(exc))
                if len(faces) == 1:
                    f = faces[0]
                    seen_face_before = True
                    if f.quality > best.get(f.angle, (0,))[0]:
                        best[f.angle] = (f.quality, frame)
                elif not faces and seen_face_before:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    no_face.append((cv2.Laplacian(gray, cv2.CV_64F).var(), idx, frame))
            cap.release()
        finally:
            tmp.unlink(missing_ok=True)
        if not best:
            raise HTTPException(422, "No face was found in the video. Film the person slowly turning around in good light.")
        added = []
        for angle, (_, frame) in best.items():
            try:
                added.append(_enroll_image(pid, frame, angle, user))
            except HTTPException:
                pass
        if len(no_face) >= 3 and ("right" in best or "left" in best):
            # the person turned their back to the camera: keep the sharpest of those frames
            no_face.sort(key=lambda t: t[0], reverse=True)
            added.append(_save_reference(pid, no_face[0][2], "back", user))
        return {"added": added, "frames_checked": frames,
                "missing": [a for a in ANGLES if a not in best]}

    @app.get("/api/references/{rid}/image")
    def reference_image(rid: int, user=viewer):
        r = db.one("SELECT image_path FROM reference_photos WHERE id = ?", (rid,))
        return FileResponse(_enrol_file(r and r["image_path"]))

    @app.delete("/api/references/{rid}")
    def delete_reference(rid: int, user=operator):
        r = db.one("SELECT * FROM reference_photos WHERE id = ?", (rid,))
        if not r:
            raise HTTPException(404, "Not found.")
        (paths.enrollments / r["image_path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM reference_photos WHERE id = ?", (rid,))
        return {"ok": True}

    @app.post("/api/faces/check")
    async def check_face(file: UploadFile = File(...), user=operator):
        """Live guide for the enrolment wizard: where is the face and which way is it turned?"""
        img = _decode_image(await file.read())
        try:
            faces = sysm.analyse_image(img)
        except ModelsMissing as exc:
            raise HTTPException(503, str(exc))
        return {"faces": [
            {"box": list(f.box), "angle": f.angle, "yaw": round(f.yaw, 2), "pitch": round(f.pitch, 2),
             "quality": f.quality, "score": round(f.score, 2)} for f in faces
        ], "width": img.shape[1], "height": img.shape[0]}

    @app.delete("/api/samples/{sid}")
    def delete_sample(sid: int, user=operator):
        s = db.one("SELECT * FROM face_samples WHERE id = ?", (sid,))
        if not s:
            raise HTTPException(404, "Not found.")
        if s["image_path"]:
            (paths.enrollments / s["image_path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM face_samples WHERE id = ?", (sid,))
        p = db.one("SELECT photo_path FROM people WHERE id = ?", (s["person_id"],))
        if p and p["photo_path"] == s["image_path"]:
            nxt = db.one("SELECT image_path FROM face_samples WHERE person_id = ? ORDER BY angle != 'front', id LIMIT 1",
                         (s["person_id"],))
            db.execute("UPDATE people SET photo_path = ? WHERE id = ?", (nxt and nxt["image_path"], s["person_id"]))
        sysm.reload_gallery()
        db.audit(user["username"], "face_delete", {"sample_id": sid})
        return {"ok": True}

    def _enrol_file(rel: str | None) -> Path:
        if not rel:
            raise HTTPException(404, "No image.")
        p = (paths.enrollments / rel).resolve()
        if paths.enrollments.resolve() not in p.parents or not p.is_file():
            raise HTTPException(404, "No image.")
        return p

    @app.get("/api/samples/{sid}/image")
    def sample_image(sid: int, user=viewer):
        s = db.one("SELECT image_path FROM face_samples WHERE id = ?", (sid,))
        return FileResponse(_enrol_file(s and s["image_path"]))

    @app.get("/api/people/{pid}/photo")
    def person_photo(pid: int, user=viewer):
        p = db.one("SELECT photo_path FROM people WHERE id = ?", (pid,))
        return FileResponse(_enrol_file(p and p["photo_path"]))

    # ------------------------------------------------------------ search / last seen
    @app.get("/api/people/{pid}/timeline")
    def timeline(pid: int, since: float = 0, until: float = 0, limit: int = 300, user=viewer):
        _person_or_404(sysm, pid)
        until = until or time.time() + 60
        rows = db.query(
            "SELECT s.*, c.map_x, c.map_y, c.floor, c.building_id, b.name AS building_name, "
            "r.start_ts AS clip_start, r.end_ts AS clip_end "
            "FROM sightings s LEFT JOIN cameras c ON c.id = s.camera_id LEFT JOIN buildings b ON b.id = c.building_id "
            "LEFT JOIN recordings r ON r.id = s.clip_id "
            "WHERE s.person_id = ? AND s.last_seen >= ? AND s.first_seen <= ? ORDER BY s.last_seen DESC LIMIT ?",
            (pid, since, until, min(limit, 2000)),
        )
        db.audit(user["username"], "timeline_view", {"person_id": pid})
        return _add_gps(sysm, rows)

    @app.get("/api/search/last-seen")
    def search_last_seen(q: str, user=viewer):
        if len(q.strip()) < 2:
            raise HTTPException(400, "Type at least 2 letters.")
        people = db.query(
            "SELECT id, full_name, person_code, category, group_name, photo_path FROM people "
            "WHERE full_name LIKE ? OR person_code LIKE ? ORDER BY full_name LIMIT 20",
            (f"%{q.strip()}%", f"%{q.strip()}%"),
        )
        for p in people:
            p["last_seen"] = _last_seen(sysm, p["id"])
        db.audit(user["username"], "search", {"q": q})
        return people

    @app.post("/api/search/photo")
    async def search_photo(file: UploadFile = File(...), user=viewer):
        img = _decode_image(await file.read())
        try:
            faces = sysm.analyse_image(img)
        except ModelsMissing as exc:
            raise HTTPException(503, str(exc))
        face = _largest(faces)
        if not face:
            raise HTTPException(422, "No face found in that photo.")
        threshold = sysm.fsetting("match_threshold", 0.40)
        out = []
        for pid, score in sysm.gallery.search(face.embedding, top_k=5):
            p = db.one("SELECT id, full_name, person_code, group_name, category, photo_path FROM people WHERE id = ?", (pid,))
            if p:
                p["similarity"] = round(score, 3)
                p["is_match"] = score >= threshold
                p["last_seen"] = _last_seen(sysm, pid)
                out.append(p)
        db.audit(user["username"], "photo_search", {"results": len(out)})
        return {"results": out, "threshold": threshold}

    @app.get("/api/sightings")
    def sightings(person_id: int | None = None, camera_id: int | None = None, unknown: bool = False,
                  since: float = 0, limit: int = 200, user=viewer):
        sql = ("SELECT s.*, p.full_name, p.group_name FROM sightings s LEFT JOIN people p ON p.id = s.person_id "
               "WHERE s.last_seen >= ?")
        params: list[Any] = [since]
        if person_id:
            sql += " AND s.person_id = ?"
            params.append(person_id)
        if camera_id:
            sql += " AND s.camera_id = ?"
            params.append(camera_id)
        if unknown:
            sql += " AND s.person_id IS NULL"
        sql += " ORDER BY s.last_seen DESC LIMIT ?"
        params.append(min(limit, 2000))
        return db.query(sql, params)

    @app.get("/api/snapshots/{rel:path}")
    def snapshot(rel: str, user=viewer):
        p = snapshot_file(paths, rel)
        if not p:
            raise HTTPException(404, "Snapshot not found (it may have been deleted by the retention policy).")
        return FileResponse(p)

    # ------------------------------------------------------------ cameras
    @app.get("/api/cameras")
    def list_cameras(user=viewer):
        return [_camera_public(sysm, c) for c in db.query("SELECT * FROM cameras ORDER BY name")]

    @app.get("/api/cameras/templates")
    def templates(user=viewer):
        return RTSP_TEMPLATES

    def _cam_values(body: CameraIn):
        kind = body.kind or detect_kind(body.source)
        analytics = json.dumps(parse_analytics(body.analytics))
        if kind not in ("usb", "rtsp", "http", "file"):
            raise HTTPException(400, "Unknown camera type.")
        if body.record_mode not in ("off", "always"):
            raise HTTPException(400, "Recording must be off or always.")
        if body.colour_mode not in COLOUR_MODES:
            raise HTTPException(400, "Colour must be off, auto or always.")
        return (body.name.strip(), body.source.strip(), kind, int(body.enabled), int(body.restricted),
                body.building_id, body.floor, body.map_x, body.map_y, body.direction % 360, body.fov, analytics,
                body.record_mode, body.colour_mode)

    @app.post("/api/cameras")
    def add_camera(body: CameraIn, user=operator):
        cid = db.execute(
            "INSERT INTO cameras(name, source, kind, enabled, restricted, building_id, floor, map_x, map_y, direction, "
            "fov, analytics, record_mode, colour_mode, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _cam_values(body) + (time.time(),),
        )
        sysm.colour.refresh_modes()
        sysm.refresh_areas()
        sysm.restart_camera(cid)
        sysm.recorder.sync_continuous()
        db.audit(user["username"], "camera_add", {"id": cid, "name": body.name})
        return {"id": cid}

    @app.put("/api/cameras/{cid}")
    def update_camera(cid: int, body: CameraIn, user=operator):
        old = db.one("SELECT * FROM cameras WHERE id = ?", (cid,))
        if not old:
            raise HTTPException(404, "Camera not found.")
        values = _cam_values(body)
        # The UI shows the masked address; keep the stored password if it was not retyped.
        if "****" in values[1]:
            values = (values[0], old["source"]) + values[2:]
        db.execute(
            "UPDATE cameras SET name=?, source=?, kind=?, enabled=?, restricted=?, building_id=?, floor=?, map_x=?, "
            "map_y=?, direction=?, fov=?, analytics=?, record_mode=?, colour_mode=? WHERE id=?",
            values + (cid,),
        )
        sysm.colour.refresh_modes()
        sysm.refresh_areas()
        sysm.restart_camera(cid)
        sysm.recorder.sync_continuous()
        db.audit(user["username"], "camera_update", {"id": cid})
        return {"ok": True}

    @app.patch("/api/cameras/{cid}/place")
    def place_camera(cid: int, body: CameraPlaceIn, user=operator):
        if not db.one("SELECT id FROM cameras WHERE id = ?", (cid,)):
            raise HTTPException(404, "Camera not found.")
        fields = {k: v for k, v in body.model_dump().items() if k in body.model_fields_set}
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            db.execute(f"UPDATE cameras SET {sets} WHERE id = ?", list(fields.values()) + [cid])
            sysm.refresh_areas()
        return {"ok": True}

    @app.put("/api/cameras/{cid}/analytics")
    def set_analytics(cid: int, body: dict, user=operator):
        if not db.one("SELECT id FROM cameras WHERE id = ?", (cid,)):
            raise HTTPException(404, "Camera not found.")
        if body.get("after_hours") and not _hours_ok(body["after_hours"]):
            raise HTTPException(400, "Closed hours must look like 18:00-06:00.")
        try:
            if "down_seconds" in body and not 5 <= float(body["down_seconds"]) <= 600:
                raise HTTPException(400, "Person down: choose 5 to 600 seconds.")
        except (TypeError, ValueError):
            raise HTTPException(400, "Person down: enter a number of seconds.")
        db.execute("UPDATE cameras SET analytics = ? WHERE id = ?", (json.dumps(parse_analytics(body)), cid))
        sysm.refresh_areas()
        db.audit(user["username"], "camera_analytics", {"id": cid, **parse_analytics(body)})
        return {"ok": True}

    @app.get("/api/analytics/defaults")
    def analytics_defaults(user=viewer):
        return {"defaults": DEFAULT_ANALYTICS, "available": sysm.activity_ok}

    @app.delete("/api/cameras/{cid}")
    def delete_camera(cid: int, user=operator):
        sysm.recorder.stop(cid)
        sysm.stop_camera(cid)
        db.execute("DELETE FROM cameras WHERE id = ?", (cid,))
        sysm.recorder.sync_continuous()
        db.audit(user["username"], "camera_delete", {"id": cid})
        return {"ok": True}

    @app.post("/api/cameras/test")
    def camera_test(body: SourceIn, user=operator):
        r = test_source(body.source.strip(), body.kind)
        jpeg = r.pop("jpeg", None)
        if jpeg:
            import base64
            r["preview"] = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
        return r

    @app.post("/api/cameras/scan")
    def camera_scan(body: ScanIn, user=operator):
        try:
            return {"devices": scan_network(body.subnet)}
        except ValueError:
            raise HTTPException(400, "Network must look like 192.168.1.0/24")

    @app.get("/api/cameras/{cid}/snapshot.jpg")
    def camera_snapshot(cid: int, user=viewer):
        jpg = sysm.render_frame(cid)
        if not jpg:
            raise HTTPException(404, "No picture from this camera yet.")
        return Response(jpg, media_type="image/jpeg")

    @app.get("/api/cameras/{cid}/stream")
    def camera_stream(cid: int, request: Request, fps: float = 8, user=viewer):
        delay = 1.0 / max(1.0, min(fps, 20.0))

        def gen():
            boundary = b"--frame\r\n"
            idle = 0
            sent_at = None
            while idle < 600:
                w = sysm.cameras.get(cid)
                stamp = w.state.last_frame_at if w else None
                if stamp is not None and stamp == sent_at:
                    # no new picture from the camera: do not draw and send the same one again
                    time.sleep(delay)
                    continue
                jpg = sysm.render_frame(cid, max_width=960)
                if jpg:
                    sent_at = stamp
                    idle = 0
                    yield boundary + b"Content-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                else:
                    idle += 1
                time.sleep(delay)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    # ------------------------------------------------------------ colour for black-and-white video
    @app.get("/api/colour")
    def colour_status(user=viewer):
        return sysm.colour.status()

    @app.post("/api/colour/download")
    def colour_download(user=admin):
        sysm.colour.start_download()
        db.audit(user["username"], "colour_ai_download")
        return sysm.colour.status()

    @app.post("/api/colour/model")
    async def colour_upload(file: UploadFile = File(...), user=admin):
        sysm.paths.user_models.mkdir(parents=True, exist_ok=True)
        tmp = sysm.paths.user_models / (COLOUR_MODEL + ".upload")
        size = 0
        with open(tmp, "wb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > 600 * 1024 * 1024:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise HTTPException(413, "That file is too large to be the colour AI.")
                f.write(chunk)
        try:
            sysm.colour.install(tmp)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        db.audit(user["username"], "colour_ai_install", {"bytes": size})
        return sysm.colour.status()

    @app.delete("/api/colour/model")
    def colour_remove(user=admin):
        sysm.colour.model_path.unlink(missing_ok=True)
        sysm.colour.load()
        db.audit(user["username"], "colour_ai_remove")
        return sysm.colour.status()

    # ------------------------------------------------------------ recordings and clips
    def _rec_or_404(rid: int) -> dict:
        r = db.one("SELECT * FROM recordings WHERE id = ?", (rid,))
        if not r:
            raise HTTPException(404, "Recording not found (it may have been deleted).")
        return r

    def _rec_out(r: dict) -> dict:
        out = dict(r)
        out.pop("path", None)
        out["duration"] = round((time.time() if r["status"] == "recording" else r["end_ts"]) - r["start_ts"], 1)
        out["ext"] = Path(r["path"]).suffix
        return out

    @app.post("/api/cameras/{cid}/record")
    def record(cid: int, body: RecordIn, user=operator):
        if not db.one("SELECT id FROM cameras WHERE id = ?", (cid,)):
            raise HTTPException(404, "Camera not found.")
        if body.action == "start":
            if sysm.camera_status(cid)["status"] != "online":
                raise HTTPException(409, "This camera is not sending pictures right now, so it cannot be recorded.")
            out = sysm.recorder.start(cid, user["username"])
            db.audit(user["username"], "record_start", {"camera_id": cid})
        elif body.action == "stop":
            out = sysm.recorder.stop(cid)
            db.audit(user["username"], "record_stop", {"camera_id": cid})
        else:
            raise HTTPException(400, "Action must be start or stop.")
        return out

    @app.get("/api/recordings")
    def recordings(camera_id: int | None = None, kind: str = "", since: float = 0, until: float = 0,
                   limit: int = 300, user=viewer):
        sql = "SELECT * FROM recordings WHERE start_ts < ? AND (end_ts >= ? OR status = 'recording')"
        params: list[Any] = [until or time.time() + 60, since]
        if camera_id:
            sql += " AND camera_id = ?"
            params.append(camera_id)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        else:
            sql += " AND kind != 'clip'"
        sql += " ORDER BY start_ts DESC LIMIT ?"
        params.append(min(limit, 2000))
        return [_rec_out(r) for r in db.query(sql, params)]

    @app.get("/api/recordings/summary")
    def recordings_summary(user=viewer):
        row = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes FROM recordings WHERE kind != 'clip'")
        clips = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes FROM recordings WHERE kind = 'clip'")
        s = db.settings()
        return {"recordings": row["n"], "recordings_mb": round(row["bytes"] / 1e6, 1),
                "clips": clips["n"], "clips_mb": round(clips["bytes"] / 1e6, 1),
                "active": {str(k): v for k, v in sysm.recorder.active().items()},
                "limit_gb": float(s.get("recording_max_gb", 50)), "days": int(float(s.get("recording_days", 7)))}

    @app.get("/api/cameras/{cid}/coverage")
    def coverage(cid: int, since: float, until: float, user=viewer):
        return sysm.recorder.coverage(cid, since, until)

    @app.get("/api/recordings/{rid}")
    def recording(rid: int, user=viewer):
        return _rec_out(_rec_or_404(rid))

    @app.patch("/api/recordings/{rid}")
    def update_recording(rid: int, body: RecordingIn, user=operator):
        _rec_or_404(rid)
        if body.keep is not None:
            db.execute("UPDATE recordings SET keep = ? WHERE id = ?", (int(body.keep), rid))
        if body.note is not None:
            db.execute("UPDATE recordings SET note = ? WHERE id = ?", (body.note.strip(), rid))
        return {"ok": True}

    @app.delete("/api/recordings/{rid}")
    def delete_recording(rid: int, user=operator):
        r = _rec_or_404(rid)
        if r["status"] == "recording":
            raise HTTPException(409, "Stop this recording first.")
        sysm.recorder.delete(r)
        db.audit(user["username"], "recording_delete", {"id": rid, "camera": r["camera_name"]})
        return {"ok": True}

    def _ready(r: dict) -> dict:
        if r["status"] == "recording" and r["camera_id"]:
            sysm.recorder.cut_open_parts(r["camera_id"])
            r = _rec_or_404(r["id"])
        if not sysm.recorder.file(r):
            raise HTTPException(404, "The video file is missing.")
        return r

    @app.get("/api/recordings/{rid}/frame.jpg")
    def recording_frame(rid: int, t: float = 0, user=viewer):
        r = _rec_or_404(rid)
        if r["status"] == "recording":
            raise HTTPException(409, "Still recording.")
        jpg = sysm.recorder.frame_at(r, t)
        if not jpg:
            raise HTTPException(404, "No picture at that time.")
        return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/recordings/{rid}/play")
    def recording_play(rid: int, start: float = 0, speed: float = 1, user=viewer):
        r = _ready(_rec_or_404(rid))
        if r["kind"] != "clip" and start < 0.5:      # log opening a video, not every jump inside it
            db.audit(user["username"], "recording_view", {"id": rid, "camera": r["camera_name"]})
        return StreamingResponse(sysm.recorder.stream(r, start, speed),
                                 media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/recordings/{rid}/download")
    def recording_download(rid: int, user=viewer):
        r = _ready(_rec_or_404(rid))
        p = sysm.recorder.file(r)
        name = f"{r['camera_name'] or 'camera'}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(r['start_ts']))}{p.suffix}"
        db.audit(user["username"], "recording_download", {"id": rid, "camera": r["camera_name"]})
        return FileResponse(p, filename=name.replace(" ", "_"), media_type="video/mp4" if p.suffix == ".mp4" else "video/x-msvideo")

    @app.get("/api/cameras/{cid}/export")
    def export_part(cid: int, start: float, end: float, user=viewer):
        if not db.one("SELECT id FROM cameras WHERE id = ?", (cid,)) and not db.one(
                "SELECT id FROM recordings WHERE camera_id = ?", (cid,)):
            raise HTTPException(404, "Camera not found.")
        tmp = paths.exports / uuid.uuid4().hex
        try:
            out, info = sysm.recorder.export(cid, start, end, tmp)
        except ValueError as exc:
            clear_tmp(tmp)
            raise HTTPException(400, str(exc))
        except LookupError as exc:
            clear_tmp(tmp)
            raise HTTPException(404, str(exc))
        db.audit(user["username"], "recording_export", {"camera_id": cid, "start": start, "end": end, **info})
        return FileResponse(out, filename=out.name, media_type="video/mp4" if out.suffix == ".mp4" else "video/x-msvideo",
                            headers={"X-CAMS-Seconds": str(info["seconds"]), "X-CAMS-Covered": str(info["covered"])},
                            background=BackgroundTask(clear_tmp, tmp))

    @app.get("/api/sightings/{sid}/clip")
    def sighting_clip(sid: int, user=viewer):
        s = db.one("SELECT clip_id FROM sightings WHERE id = ?", (sid,))
        if not s or not s["clip_id"]:
            raise HTTPException(404, "There is no clip of this sighting.")
        return _rec_out(_rec_or_404(s["clip_id"]))

    # ------------------------------------------------------------ map builder
    @app.get("/api/map")
    def get_map(user=viewer):
        s = db.settings()
        img = s.get("map_image", "")
        g = geo.georef_from_settings(s)
        return {
            "image": f"/api/map/image?v={s.get('map_image_v', '0')}" if img else None,
            "image_source": s.get("map_image_source", "") if img else "",
            "attribution": geo.ATTRIBUTION if img and s.get("map_image_source") == "satellite" else "",
            "geo": {"lat": g.lat, "lng": g.lng} if g else None,
            "width_m": float(s.get("map_width_m", 200)),
            "height_m": float(s.get("map_height_m", 150)),
            "buildings": [_building_out(b) for b in db.query("SELECT * FROM buildings ORDER BY id")],
            "cameras": [
                {k: c[k] for k in ("id", "name", "map_x", "map_y", "direction", "fov", "floor", "building_id",
                                   "restricted", "enabled")}
                | {"live": sysm.camera_status(c["id"]), "analytics": parse_analytics(c["analytics"])}
                for c in db.query("SELECT * FROM cameras ORDER BY name")
            ],
        }

    @app.put("/api/map")
    def set_map(body: MapIn, user=operator):
        db.set_settings({"map_width_m": body.width_m, "map_height_m": body.height_m})
        return {"ok": True}

    @app.post("/api/map/image")
    async def upload_map(file: UploadFile = File(...), user=operator):
        img = _decode_image(await file.read())
        h, w = img.shape[:2]
        if w > 4096:
            img = cv2.resize(img, (4096, int(h * 4096 / w)))
        target = paths.maps / "site.jpg"
        cv2.imwrite(str(target), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        db.set_settings({"map_image": "site.jpg", "map_image_v": int(time.time()),
                         "map_image_w": img.shape[1], "map_image_h": img.shape[0], "map_image_source": "upload"})
        db.audit(user["username"], "map_upload")
        return {"ok": True, "width_px": img.shape[1], "height_px": img.shape[0]}

    @app.delete("/api/map/image")
    def delete_map_image(user=operator):
        (paths.maps / "site.jpg").unlink(missing_ok=True)
        db.set_settings({"map_image": "", "map_image_source": ""})
        return {"ok": True}

    @app.get("/api/map/image")
    def map_image(user=viewer):
        p = paths.maps / "site.jpg"
        if not p.is_file():
            raise HTTPException(404, "No map image uploaded.")
        return FileResponse(p)

    # ------------------------------------------------------------ real-world position + satellite
    @app.get("/api/geo")
    def get_geo(user=viewer):
        s = db.settings()
        g = geo.georef_from_settings(s)
        return {"lat": g.lat if g else None, "lng": g.lng if g else None,
                "width_m": float(s.get("map_width_m", 200)), "height_m": float(s.get("map_height_m", 150)),
                "satellite": s.get("map_image_source") == "satellite" and bool(s.get("map_image")),
                "attribution": geo.ATTRIBUTION, "tiles_mb": round(sysm.tiles.size_bytes() / 1e6, 1)}

    @app.put("/api/geo")
    def set_geo(body: GeoIn, user=operator):
        if (body.lat is None) != (body.lng is None):
            raise HTTPException(400, "Give both latitude and longitude.")
        db.set_settings({"geo_lat": "" if body.lat is None else body.lat, "geo_lng": "" if body.lng is None else body.lng})
        db.audit(user["username"], "map_location", {"lat": body.lat, "lng": body.lng})
        return {"ok": True}

    @app.get("/api/geo/parse")
    def parse_geo(text: str, user=viewer):
        r = geo.parse_location(text)
        if not r:
            raise HTTPException(400, "CAMS could not read a position from that. Type it like -6.7701, 39.2405 or paste a Google Maps link.")
        return {"lat": r[0], "lng": r[1]}

    @app.get("/api/geo/search")
    def search_place(q: str, user=operator):
        if len(q.strip()) < 2:
            raise HTTPException(400, "Type a place name.")
        r = geo.parse_location(q)
        if r:
            return [{"name": f"{r[0]:.6f}, {r[1]:.6f}", "lat": r[0], "lng": r[1]}]
        try:
            return geo.search_places(q.strip())
        except geo.GeoError as exc:
            raise HTTPException(503, str(exc))

    @app.get("/api/geo/tiles/{source}/{z}/{x}/{y}")
    def geo_tile(source: str, z: int, x: int, y: int, user=viewer):
        try:
            data = sysm.tiles.get(source, z, x, y)
        except geo.GeoError as exc:
            raise HTTPException(404, str(exc))
        if not data:
            raise HTTPException(404, "Tile not available (no internet and not saved before).")
        media = "image/png" if geo.SOURCES[source][1] == "png" else "image/jpeg"
        return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=604800"})

    @app.post("/api/geo/satellite")
    def make_satellite(body: SatelliteIn, user=operator):
        try:
            img, info = geo.satellite_picture(sysm.tiles, body.lat, body.lng, body.width_m, body.height_m)
        except geo.GeoError as exc:
            raise HTTPException(503, str(exc))
        target = paths.maps / "site.jpg"
        old = db.settings()
        if (paths.maps / "site.jpg").is_file() and old.get("map_image_source") != "satellite":
            shutil.copy2(target, paths.maps / "site-before-satellite.jpg")
        cv2.imwrite(str(target), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        # keep what was drawn in the same place on the ground when the map size changes
        if body.keep_buildings:
            ow, oh = float(old.get("map_width_m", 200)), float(old.get("map_height_m", 150))
            dx, dy = (body.width_m - ow) / 2, (body.height_m - oh) / 2
            og = geo.georef_from_settings(old)
            if og:  # map was already on Earth: move drawings so they stay on the same spot
                ng = geo.Georef(body.lat, body.lng, body.width_m, body.height_m)
                cx, cy = ng.to_map(*og.to_latlng(ow / 2, oh / 2))
                dx, dy = cx - ow / 2, cy - oh / 2
            if abs(dx) > 0.05 or abs(dy) > 0.05:
                for b in db.query("SELECT id, polygon FROM buildings"):
                    pts = [[round(x + dx, 1), round(y + dy, 1)] for x, y in json.loads(b["polygon"])]
                    db.execute("UPDATE buildings SET polygon = ? WHERE id = ?", (json.dumps(pts), b["id"]))
                db.execute("UPDATE cameras SET map_x = map_x + ?, map_y = map_y + ? WHERE map_x IS NOT NULL", (dx, dy))
                sysm.refresh_areas()
        db.set_settings({"map_image": "site.jpg", "map_image_v": int(time.time()), "map_image_source": "satellite",
                         "map_image_w": img.shape[1], "map_image_h": img.shape[0],
                         "map_width_m": round(body.width_m, 1), "map_height_m": round(body.height_m, 1),
                         "geo_lat": round(body.lat, 7), "geo_lng": round(body.lng, 7)})
        db.audit(user["username"], "map_satellite", {"lat": body.lat, "lng": body.lng, **info})
        return {"ok": True, **info}

    # 3D map drawn in Map Studio: a JSON document of shapes, roofs, stairs, paint...
    SCENE_MAX = 30 * 1024 * 1024

    @app.get("/api/map/scene")
    def get_scene(user=viewer):
        p = paths.maps / "scene.json"
        if not p.is_file():
            return {"version": 1, "objects": [], "paint": None}
        return FileResponse(p, media_type="application/json", headers={"Cache-Control": "no-store"})

    @app.put("/api/map/scene")
    async def set_scene(request: Request, user=operator):
        raw = await request.body()
        if len(raw) > SCENE_MAX:
            raise HTTPException(413, "The map is too large to save (max 30 MB). Clear some ground paint.")
        try:
            doc = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "The map data is not valid.")
        if not isinstance(doc, dict) or not isinstance(doc.get("objects"), list):
            raise HTTPException(400, "The map data is not valid.")
        if len(doc["objects"]) > 50000:
            raise HTTPException(400, "Too many objects (max 50000).")
        if any(not isinstance(o, dict) or not isinstance(o.get("type"), str) for o in doc["objects"]):
            raise HTTPException(400, "The map data is not valid.")
        paint = doc.get("paint")
        if paint is not None and not (isinstance(paint, str) and paint.startswith("data:image/png;base64,")):
            raise HTTPException(400, "Ground paint must be a PNG image.")
        target = paths.maps / "scene.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(target)
        db.audit(user["username"], "map_scene_save", {"objects": len(doc["objects"])})
        return {"ok": True, "objects": len(doc["objects"])}

    def _check_building(body: BuildingIn):
        if len(body.polygon) < 3 or any(len(pt) != 2 for pt in body.polygon):
            raise HTTPException(400, "A shape needs at least 3 corner points.")
        if body.kind not in ("building", "zone", "gate", "field", "parking"):
            raise HTTPException(400, "Unknown shape type.")
        if body.access_mode not in ("everyone", "allow", "deny"):
            raise HTTPException(400, "Access must be everyone, allow or deny.")
        if body.closed_hours and not _hours_ok(body.closed_hours):
            raise HTTPException(400, "Closed hours must look like 18:00-06:00.")

    def _building_values(body: BuildingIn):
        floors = max(1, min(body.floors, 200))
        names = [n.strip()[:40] for n in body.floor_names][:floors]
        return (body.name, body.kind, json.dumps(body.polygon), body.height_m, floors, body.color,
                body.rotation % 360, json.dumps(names), body.access_mode, json.dumps(body.access_categories),
                json.dumps(body.access_groups), json.dumps([int(x) for x in body.access_people]),
                body.closed_hours.strip(), body.purpose if body.purpose in PURPOSES else "")

    @app.post("/api/buildings")
    def add_building(body: BuildingIn, user=operator):
        _check_building(body)
        bid = db.execute(
            "INSERT INTO buildings(name, kind, polygon, height_m, floors, color, rotation, floor_names, access_mode, "
            "access_categories, access_groups, access_people, closed_hours, purpose) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _building_values(body),
        )
        sysm.refresh_areas()
        db.audit(user["username"], "area_add", {"id": bid, "name": body.name})
        return {"id": bid}

    @app.put("/api/buildings/{bid}")
    def update_building(bid: int, body: BuildingIn, user=operator):
        _check_building(body)
        old = db.one("SELECT access_mode, access_categories, access_groups, access_people, closed_hours FROM buildings WHERE id = ?", (bid,))
        db.execute(
            "UPDATE buildings SET name=?, kind=?, polygon=?, height_m=?, floors=?, color=?, rotation=?, floor_names=?, "
            "access_mode=?, access_categories=?, access_groups=?, access_people=?, closed_hours=?, purpose=? WHERE id=?",
            _building_values(body) + (bid,),
        )
        sysm.refresh_areas()
        new = db.one("SELECT access_mode, access_categories, access_groups, access_people, closed_hours FROM buildings WHERE id = ?", (bid,))
        if old != new:
            db.audit(user["username"], "area_rules", {"id": bid, "name": body.name, **(new or {})})
        return {"ok": True}

    @app.delete("/api/buildings/{bid}")
    def delete_building(bid: int, user=operator):
        db.execute("DELETE FROM buildings WHERE id = ?", (bid,))
        sysm.refresh_areas()
        return {"ok": True}

    # ------------------------------------------------------------ alerts
    @app.get("/api/alerts")
    def alerts(open_only: bool = True, limit: int = 100, user=viewer):
        sql = ("SELECT a.*, COALESCE(a.snapshot_path, s.snapshot_path) AS snapshot_path, p.full_name, "
               "c.name AS camera_name FROM alerts a LEFT JOIN sightings s ON s.id = a.sighting_id "
               "LEFT JOIN cameras c ON c.id = a.camera_id "
               "LEFT JOIN people p ON p.id = a.person_id")
        if open_only:
            sql += " WHERE a.acknowledged = 0"
        sql += " ORDER BY a.created_at DESC LIMIT ?"
        return db.query(sql, (min(limit, 1000),))

    @app.get("/api/alerts/emergencies")
    def open_emergencies(user=viewer):
        """Open fire / smoke / person-down alerts: every CAMS window shows these full screen."""
        return db.query(
            "SELECT a.*, c.name AS camera_name FROM alerts a LEFT JOIN cameras c ON c.id = a.camera_id "
            "WHERE a.acknowledged = 0 AND a.kind IN ('fire', 'smoke', 'person_down', 'emergency_test') "
            "ORDER BY a.created_at DESC LIMIT 20")

    @app.post("/api/alerts/{aid}/ack")
    def ack(aid: int, user=viewer):
        db.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (aid,))
        return {"ok": True}

    @app.post("/api/alerts/test-emergency")
    def test_emergency(user=admin):
        """Try the emergency warning: the red screen and the alarm on every CAMS window and this PC."""
        sysm._alert("emergency_test", "TEST of the emergency alarm. Nothing is wrong: press I'm handling it to stop it.", None, None, None)
        db.audit(user["username"], "emergency_test")
        return {"ok": True}

    @app.post("/api/alerts/ack-all")
    def ack_all(user=viewer):
        db.execute("UPDATE alerts SET acknowledged = 1 WHERE acknowledged = 0")
        db.audit(user["username"], "alerts_ack_all")
        return {"ok": True}

    # ------------------------------------------------------------ settings / admin
    EDITABLE = {"site_name", "match_threshold", "analysis_fps", "sighting_merge_seconds", "retention_days",
                "blur_unknown", "save_snapshots", "workers", "onboarding_done", "map_mode", "activity_ai", "daily_summary_time",
                "map_mouse", "sighting_clips", "clip_seconds", "record_fps", "record_width", "recording_days",
                "recording_max_gb", "colour_enhance", "colour_refresh", "speed_mode", "route_hours", "alert_days",
                "min_free_gb", "tiles_max_mb", "emergency_sensitivity", "alarm_sound"}
    PERSONAL = {"onboarding_done", "map_mode", "map_mouse"}     # anyone signed in may change these

    @app.get("/api/settings")
    def get_settings(user=viewer):
        s = db.settings()
        return {k: s.get(k) for k in EDITABLE}

    @app.put("/api/settings")
    def put_settings(body: dict, user=Depends(current_user)):
        values = {k: v for k, v in body.items() if k in EDITABLE}
        if set(values) - PERSONAL and not auth.role_at_least(user, "admin"):
            raise HTTPException(403, "Only an admin can change settings.")
        try:
            if "match_threshold" in values and not 0.25 <= float(values["match_threshold"]) <= 0.9:
                raise HTTPException(400, "Match threshold must be between 0.25 and 0.90.")
            if "analysis_fps" in values and not 0.2 <= float(values["analysis_fps"]) <= 15:
                raise HTTPException(400, "Analysis speed must be 0.2 to 15 frames per second.")
            if "daily_summary_time" in values and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(values["daily_summary_time"])):
                raise HTTPException(400, "Daily summary time must look like 20:30.")
            if "activity_ai" in values and str(values["activity_ai"]) not in ("0", "1"):
                raise HTTPException(400, "Activity AI must be on or off.")
            if "retention_days" in values and not 0 <= int(values["retention_days"]) <= 3650:
                raise HTTPException(400, "Keep the activity timeline for 1 to 3650 days (0 = keep).")
            if "alert_days" in values and not 0 <= int(values["alert_days"]) <= 3650:
                raise HTTPException(400, "Keep alerts for 1 to 3650 days (0 = keep).")
            if "route_hours" in values and not 0 <= float(values["route_hours"]) <= 24 * 3650:
                raise HTTPException(400, "Keep routes for 1 hour or more (0 = keep).")
            if "emergency_sensitivity" in values and values["emergency_sensitivity"] not in ("low", "normal", "high"):
                raise HTTPException(400, "Emergency sensitivity must be low, normal or high.")
            if "alarm_sound" in values and str(values["alarm_sound"]) not in ("0", "1"):
                raise HTTPException(400, "Alarm sound must be on or off.")
            if "speed_mode" in values and values["speed_mode"] not in ("auto", "fast", "balanced", "detailed"):
                raise HTTPException(400, "Face AI speed must be auto, fast, balanced or detailed.")
            if "min_free_gb" in values and not 0 <= float(values["min_free_gb"]) <= 1000:
                raise HTTPException(400, "Free space to keep must be 0 to 1000 GB.")
            if "tiles_max_mb" in values and not 20 <= float(values["tiles_max_mb"]) <= 100000:
                raise HTTPException(400, "Saved map space must be 20 MB or more.")
            if "map_mouse" in values and values["map_mouse"] not in ("standard", "swapped"):
                raise HTTPException(400, "Mouse buttons must be standard or swapped.")
            if "sighting_clips" in values and str(values["sighting_clips"]) not in ("0", "1"):
                raise HTTPException(400, "Sighting clips must be on or off.")
            if "clip_seconds" in values and not 3 <= float(values["clip_seconds"]) <= 30:
                raise HTTPException(400, "Clips must be 3 to 30 seconds long.")
            if "record_fps" in values and not 1 <= float(values["record_fps"]) <= 25:
                raise HTTPException(400, "Record 1 to 25 pictures a second.")
            if "record_width" in values and int(values["record_width"]) not in (640, 960, 1280, 1920):
                raise HTTPException(400, "Recording size must be 640, 960, 1280 or 1920 wide.")
            if "colour_enhance" in values and str(values["colour_enhance"]) not in ("0", "1"):
                raise HTTPException(400, "Clearer night pictures must be on or off.")
            if "colour_refresh" in values and not 0.15 <= float(values["colour_refresh"]) <= 10:
                raise HTTPException(400, "Colour refresh must be 0.15 to 10 seconds.")
            if "recording_days" in values and not 0 <= int(values["recording_days"]) <= 365:
                raise HTTPException(400, "Keep recordings for 1 to 365 days (0 = keep).")
            if "recording_max_gb" in values and not 1 <= float(values["recording_max_gb"]) <= 20000:
                raise HTTPException(400, "The recording space must be 1 to 20000 GB.")
        except ValueError:
            raise HTTPException(400, "Please enter a number.")
        db.set_settings(values)
        sysm.invalidate_settings()
        if set(values) - PERSONAL:
            db.audit(user["username"], "settings", values)
        return {"ok": True}

    @app.get("/api/audit")
    def audit(limit: int = 300, user=admin):
        return db.query("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (min(limit, 5000),))

    @app.post("/api/maintenance/purge")
    def purge(user=admin):
        n = sysm.purge_old()
        db.audit(user["username"], "purge", {"deleted": n})
        return {"deleted": n}

    @app.get("/api/data/usage")
    def data_usage(user=admin):
        out = sysm.data_usage()
        out["speed_mode"] = sysm.speed_mode()
        out["stats"] = {k: sysm.stats.get(k, 0) for k in ("frames_analysed", "frames_skipped", "prints_reused")}
        return out

    @app.post("/api/data/delete")
    def data_delete(body: dict, user=admin):
        kinds = [k for k in (body.get("kinds") or []) if k in sysm.DATA_KINDS]
        if not kinds:
            raise HTTPException(400, "Choose what to delete.")
        out = sysm.delete_now(kinds)
        db.audit(user["username"], "data_delete", out)
        return {"deleted": out}

    @app.get("/api/backup")
    def backup(user=admin):
        """Zip of the database, enrolment photos and map (snapshots excluded)."""
        buf = io.BytesIO()
        tmp = paths.data / "backup_tmp.db"
        with db.conn() as src:
            import sqlite3
            dst = sqlite3.connect(tmp)
            src.backup(dst)
            dst.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp, "cams.db")
            for folder in (paths.enrollments, paths.maps):
                for f in folder.rglob("*"):
                    if f.is_file():
                        z.write(f, str(f.relative_to(paths.data)))
        tmp.unlink(missing_ok=True)
        db.audit(user["username"], "backup")
        stamp = time.strftime("%Y%m%d-%H%M")
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="cams-backup-{stamp}.zip"'})

    # ------------------------------------------------------------ errors + UI
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:]) or "input"
        return JSONResponse({"error": f"{field.replace('_', ' ')}: {first.get('msg', 'invalid value')}"}, status_code=422)

    static = paths.static
    # ------------------------------------------------------------ activity AI
    ins = sysm.insights

    def _reload_ai():
        if sysm.behaviour:
            sysm.behaviour.reload()

    def _key_for(label: str) -> str:
        """Turn a typed activity name into a known key (or the label itself for new ones)."""
        lab = label.strip()
        for k, v in ins.labels().items():
            if lab.lower() in (k.lower(), v.lower()):
                return k
        return lab

    def _day(day: str | None) -> str:
        if not day:
            return day_str()
        try:
            time.strptime(day, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "Day must look like 2026-10-28.")
        return day

    @app.get("/api/activity/status")
    def activity_status(user=viewer):
        b = sysm.behaviour
        taught = db.query("SELECT label, COUNT(*) AS n FROM activity_examples WHERE label IS NOT NULL GROUP BY label ORDER BY n DESC")
        return {
            "available": b is not None, "enabled": sysm.setting("activity_ai") != "0", "pose": bool(b and b.pose_ok),
            "labels": ins.labels(), "builtin": list(BUILTIN), "purposes": PURPOSES,
            "taught": [{"key": r["label"], "label": ins.label(r["label"]), "examples": r["n"]} for r in taught],
            "today_entries": db.one("SELECT COUNT(*) AS n FROM activity_log WHERE start_ts >= ?", (time.mktime(time.strptime(day_str(), "%Y-%m-%d")),))["n"],
            "areas": ins.areas(),
            "summary_time": sysm.setting("daily_summary_time") or "20:30",
        }

    @app.get("/api/people/{pid}/day")
    def person_day(pid: int, day: str | None = None, user=viewer):
        p = _person_or_404(sysm, pid)
        day = _day(day)
        a, b = day_bounds(day)
        rows = ins.timeline(pid, a, b)
        for r in rows:
            r["label"] = ins.label(r["activity"])
        return {
            "day": day, "entries": rows, "visits": ins.visits(pid, a, b), "notes": ins.notes(pid, day),
            "summary": ins.summary_text(p, day), "habits": ins.habits(pid, 21),
        }

    @app.put("/api/activity/entries/{eid}")
    def correct_entry(eid: int, body: LabelIn, user=operator):
        row = db.one("SELECT * FROM activity_log WHERE id = ?", (eid,))
        if not row:
            raise HTTPException(404, "Timeline entry not found.")
        if not body.label:
            raise HTTPException(400, "Choose what the person was doing.")
        key = _key_for(body.label)
        db.execute("UPDATE activity_log SET activity = ?, source = 'corrected' WHERE id = ?", (key, eid))
        if row["example_id"]:
            db.execute("UPDATE activity_examples SET label = ? WHERE id = ?", (key, row["example_id"]))
        _ensure_type(key)
        _reload_ai()
        db.audit(user["username"], "activity_correct", {"entry": eid, "label": key})
        return {"ok": True, "label": ins.label(key)}

    def _ensure_type(key: str):
        if key not in BUILTIN and not db.one("SELECT 1 FROM activity_types WHERE key = ?", (key,)):
            db.execute("INSERT OR IGNORE INTO activity_types(key, label, created_at) VALUES (?,?,?)", (key, key, time.time()))

    @app.get("/api/activity/types")
    def activity_types(user=viewer):
        return [{"key": k, "label": v, "builtin": k in BUILTIN} for k, v in ins.labels().items()]

    @app.post("/api/activity/types")
    def add_activity_type(body: ActivityTypeIn, user=operator):
        key = body.label.strip()
        if _key_for(key) != key or key in BUILTIN:
            raise HTTPException(409, "That activity already exists.")
        db.execute("INSERT OR IGNORE INTO activity_types(key, label, created_at) VALUES (?,?,?)", (key, key, time.time()))
        return {"key": key}

    @app.delete("/api/activity/types/{key}")
    def delete_activity_type(key: str, user=operator):
        if key in BUILTIN:
            raise HTTPException(400, "Built-in activities cannot be removed.")
        db.execute("DELETE FROM activity_types WHERE key = ?", (key,))
        db.execute("UPDATE activity_examples SET label = NULL WHERE label = ?", (key,))
        _reload_ai()
        return {"ok": True}

    @app.get("/api/activity/examples")
    def activity_examples(auto: str = "", label: str = "", unlabelled: bool = False, person_id: int | None = None, limit: int = 60, user=operator):
        sql = ("SELECT e.id, e.ts, e.camera_id, e.person_id, e.auto_label, e.label, e.image_path, p.full_name FROM activity_examples e "
               "LEFT JOIN people p ON p.id = e.person_id WHERE e.image_path IS NOT NULL")
        args: list = []
        if auto:
            sql += " AND e.auto_label = ?"; args.append(auto)
        if label:
            sql += " AND e.label = ?"; args.append(label)
        if unlabelled:
            sql += " AND e.label IS NULL"
        if person_id:
            sql += " AND e.person_id = ?"; args.append(person_id)
        rows = db.query(sql + " ORDER BY e.ts DESC LIMIT ?", args + [max(1, min(limit, 300))])
        for r in rows:
            r["auto_text"] = ins.label(r["auto_label"]); r["label_text"] = ins.label(r["label"]) if r["label"] else None
        return rows

    @app.put("/api/activity/examples/{xid}")
    def label_example(xid: int, body: LabelIn, user=operator):
        if not db.one("SELECT 1 FROM activity_examples WHERE id = ?", (xid,)):
            raise HTTPException(404, "Example not found.")
        key = _key_for(body.label) if body.label else None
        db.execute("UPDATE activity_examples SET label = ? WHERE id = ?", (key, xid))
        if key:
            _ensure_type(key)
            db.execute("UPDATE activity_log SET activity = ?, source = 'corrected' WHERE example_id = ?", (key, xid))
        _reload_ai()
        return {"ok": True}

    @app.delete("/api/activity/examples/{xid}")
    def delete_example(xid: int, user=operator):
        r = db.one("SELECT image_path FROM activity_examples WHERE id = ?", (xid,))
        if r and r["image_path"] and not db.one("SELECT 1 FROM activity_log WHERE image_path = ?", (r["image_path"],)):
            (paths.snapshots / r["image_path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM activity_examples WHERE id = ?", (xid,))
        _reload_ai()
        return {"ok": True}

    def _rule_out(r):
        r = dict(r)
        r["area_ids"] = json.loads(r["area_ids"] or "[]"); r["days"] = json.loads(r["days"] or "[]")
        r["label"] = ins.label(r["activity"])
        return r

    @app.get("/api/activity/rules")
    def activity_rules(user=viewer):
        return [_rule_out(r) for r in db.query("SELECT * FROM activity_rules ORDER BY start")]

    def _rule_values(b: ActivityRuleIn):
        if b.body not in ("any", "sitting", "standing", "moving"):
            raise HTTPException(400, "Body must be any, sitting, standing or moving.")
        key = _key_for(b.activity)
        _ensure_type(key)
        return (key, json.dumps(b.area_ids), b.purpose if b.purpose in PURPOSES else "", b.start, b.end,
                json.dumps(sorted({d for d in b.days if 0 <= d <= 6})), b.body, int(b.enabled))

    @app.post("/api/activity/rules")
    def add_activity_rule(body: ActivityRuleIn, user=operator):
        rid = db.execute("INSERT INTO activity_rules(activity, area_ids, purpose, start, end, days, body, enabled) VALUES (?,?,?,?,?,?,?,?)", _rule_values(body))
        _reload_ai()
        return {"id": rid}

    @app.put("/api/activity/rules/{rid}")
    def update_activity_rule(rid: int, body: ActivityRuleIn, user=operator):
        db.execute("UPDATE activity_rules SET activity=?, area_ids=?, purpose=?, start=?, end=?, days=?, body=?, enabled=? WHERE id=?", _rule_values(body) + (rid,))
        _reload_ai()
        return {"ok": True}

    @app.delete("/api/activity/rules/{rid}")
    def delete_activity_rule(rid: int, user=operator):
        db.execute("DELETE FROM activity_rules WHERE id = ?", (rid,))
        _reload_ai()
        return {"ok": True}

    @app.get("/api/routines")
    def routines(user=viewer):
        out = ins.routine_rows()
        for r in out:
            r["place"] = ins.place_words(r)
        return out

    def _routine_values(b: RoutineIn):
        if b.expect not in ("present", "absent"):
            raise HTTPException(400, "Expect must be present or absent.")
        if not b.area_ids and not b.purpose:
            raise HTTPException(400, "Choose the place (an area, or a kind of place such as Dining hall).")
        return (b.name.strip(), b.start, b.end, json.dumps(sorted({d for d in b.days if 0 <= d <= 6})), json.dumps(b.area_ids),
                b.purpose if b.purpose in PURPOSES else "", b.expect, json.dumps(b.who_categories), json.dumps(b.who_groups),
                json.dumps([int(x) for x in b.who_people]), b.grace_min, int(b.alert), int(b.enabled))

    @app.post("/api/routines")
    def add_routine(body: RoutineIn, user=operator):
        rid = db.execute("INSERT INTO routines(name, start, end, days, area_ids, purpose, expect, who_categories, who_groups, who_people, "
                         "grace_min, alert, enabled) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", _routine_values(body))
        db.audit(user["username"], "routine_add", {"id": rid, "name": body.name})
        return {"id": rid}

    @app.put("/api/routines/{rid}")
    def update_routine(rid: int, body: RoutineIn, user=operator):
        db.execute("UPDATE routines SET name=?, start=?, end=?, days=?, area_ids=?, purpose=?, expect=?, who_categories=?, who_groups=?, "
                   "who_people=?, grace_min=?, alert=?, enabled=?, checked_day='' WHERE id=?", _routine_values(body) + (rid,))
        return {"ok": True}

    @app.delete("/api/routines/{rid}")
    def delete_routine(rid: int, user=operator):
        db.execute("DELETE FROM routines WHERE id = ?", (rid,))
        db.execute("DELETE FROM person_notes WHERE routine_id = ?", (rid,))
        return {"ok": True}

    @app.post("/api/routines/{rid}/check")
    def check_routine_now(rid: int, day: str | None = None, user=operator):
        r = next((x for x in ins.routine_rows() if x["id"] == rid), None)
        if not r:
            raise HTTPException(404, "Routine not found.")
        res = ins.check_routine(r, _day(day))
        return {"checked": len(res), "counts": dict(Counter(x["kind"] for x in res))}

    @app.get("/api/report/daily")
    def daily_report(day: str | None = None, category: str = "", group: str = "", all: bool = False, user=viewer):
        return ins.report(_day(day), category, group, all)

    @app.get("/api/report/daily.csv")
    def daily_report_csv(day: str | None = None, category: str = "", group: str = "", all: bool = False, user=viewer):
        day = _day(day)
        data = ins.report_csv(ins.report(day, category, group, all))
        return Response("\ufeff" + data, media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="cams-daily-report-{day}.csv"'})

    @app.post("/api/report/daily/summaries")
    def write_summaries(day: str | None = None, user=operator):
        day = _day(day)
        for r in ins.routine_rows():
            if r["enabled"] and (not r["days"] or datetime.strptime(day, "%Y-%m-%d").weekday() in r["days"]):
                if day_at(day, r["end"]) < time.time():
                    ins.check_routine(r, day)
        n = ins.write_day_summaries(day)
        return {"people": n}

    @app.post("/api/ask")
    def ask(body: AskIn, user=viewer):
        db.audit(user["username"], "ask", {"q": body.question[:120]})
        return ins.ask(body.question)

    # Always check the screen files with the server (cheap 304s), so an update shows at once
    # instead of the window reusing the previous version's copies.
    @app.middleware("http")
    async def no_stale_screens(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        sysm.stats["ui_loads"] = sysm.stats.get("ui_loads", 0) + 1
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app
