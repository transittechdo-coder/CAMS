"""HTTP API used by the CAMS user interface.

Everything runs on this computer (http://127.0.0.1:8765 by default); no data
leaves the local network.
"""

from __future__ import annotations

import csv
import io
import json
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
from .face_engine import ALL_ANGLES, ANGLES, REFERENCE_ANGLES, ModelsMissing
from .system import CamsSystem, snapshot_file

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


class MapIn(BaseModel):
    width_m: float = Field(gt=1, le=20000)
    height_m: float = Field(gt=1, le=20000)


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
    return out


def _last_seen(sysm: CamsSystem, pid: int) -> dict | None:
    row = sysm.db.one(
        "SELECT s.*, c.map_x, c.map_y, c.floor, c.building_id, b.name AS building_name "
        "FROM sightings s LEFT JOIN cameras c ON c.id = s.camera_id "
        "LEFT JOIN buildings b ON b.id = c.building_id "
        "WHERE s.person_id = ? ORDER BY s.last_seen DESC LIMIT 1",
        (pid,),
    )
    return row


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
            "site_name": db.get_setting("site_name"),
            "user": user and {k: user[k] for k in ("id", "username", "full_name", "role")},
            "onboarding_done": db.get_setting("onboarding_done") == "1",
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
        shutil.rmtree(paths.enrollments / str(pid), ignore_errors=True)
        db.execute("DELETE FROM people WHERE id = ?", (pid,))
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
            "SELECT s.*, c.map_x, c.map_y, c.floor, c.building_id, b.name AS building_name "
            "FROM sightings s LEFT JOIN cameras c ON c.id = s.camera_id LEFT JOIN buildings b ON b.id = c.building_id "
            "WHERE s.person_id = ? AND s.last_seen >= ? AND s.first_seen <= ? ORDER BY s.last_seen DESC LIMIT ?",
            (pid, since, until, min(limit, 2000)),
        )
        db.audit(user["username"], "timeline_view", {"person_id": pid})
        return rows

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
        return (body.name.strip(), body.source.strip(), kind, int(body.enabled), int(body.restricted),
                body.building_id, body.floor, body.map_x, body.map_y, body.direction % 360, body.fov, analytics)

    @app.post("/api/cameras")
    def add_camera(body: CameraIn, user=operator):
        cid = db.execute(
            "INSERT INTO cameras(name, source, kind, enabled, restricted, building_id, floor, map_x, map_y, direction, "
            "fov, analytics, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _cam_values(body) + (time.time(),),
        )
        sysm.refresh_areas()
        sysm.restart_camera(cid)
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
            "map_y=?, direction=?, fov=?, analytics=? WHERE id=?",
            values + (cid,),
        )
        sysm.refresh_areas()
        sysm.restart_camera(cid)
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
        db.execute("UPDATE cameras SET analytics = ? WHERE id = ?", (json.dumps(parse_analytics(body)), cid))
        sysm.refresh_areas()
        db.audit(user["username"], "camera_analytics", {"id": cid, **parse_analytics(body)})
        return {"ok": True}

    @app.get("/api/analytics/defaults")
    def analytics_defaults(user=viewer):
        return {"defaults": DEFAULT_ANALYTICS, "available": sysm.activity_ok}

    @app.delete("/api/cameras/{cid}")
    def delete_camera(cid: int, user=operator):
        sysm.stop_camera(cid)
        db.execute("DELETE FROM cameras WHERE id = ?", (cid,))
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
            while idle < 600:
                jpg = sysm.render_frame(cid, max_width=960)
                if jpg:
                    idle = 0
                    yield boundary + b"Content-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                else:
                    idle += 1
                time.sleep(delay)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    # ------------------------------------------------------------ map builder
    @app.get("/api/map")
    def get_map(user=viewer):
        s = db.settings()
        img = s.get("map_image", "")
        return {
            "image": f"/api/map/image?v={s.get('map_image_v', '0')}" if img else None,
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
                         "map_image_w": img.shape[1], "map_image_h": img.shape[0]})
        db.audit(user["username"], "map_upload")
        return {"ok": True, "width_px": img.shape[1], "height_px": img.shape[0]}

    @app.delete("/api/map/image")
    def delete_map_image(user=operator):
        (paths.maps / "site.jpg").unlink(missing_ok=True)
        db.set_settings({"map_image": ""})
        return {"ok": True}

    @app.get("/api/map/image")
    def map_image(user=viewer):
        p = paths.maps / "site.jpg"
        if not p.is_file():
            raise HTTPException(404, "No map image uploaded.")
        return FileResponse(p)

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
                body.closed_hours.strip())

    @app.post("/api/buildings")
    def add_building(body: BuildingIn, user=operator):
        _check_building(body)
        bid = db.execute(
            "INSERT INTO buildings(name, kind, polygon, height_m, floors, color, rotation, floor_names, access_mode, "
            "access_categories, access_groups, access_people, closed_hours) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            "access_mode=?, access_categories=?, access_groups=?, access_people=?, closed_hours=? WHERE id=?",
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

    @app.post("/api/alerts/{aid}/ack")
    def ack(aid: int, user=viewer):
        db.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (aid,))
        return {"ok": True}

    @app.post("/api/alerts/ack-all")
    def ack_all(user=viewer):
        db.execute("UPDATE alerts SET acknowledged = 1 WHERE acknowledged = 0")
        db.audit(user["username"], "alerts_ack_all")
        return {"ok": True}

    # ------------------------------------------------------------ settings / admin
    EDITABLE = {"site_name", "match_threshold", "analysis_fps", "sighting_merge_seconds", "retention_days",
                "blur_unknown", "save_snapshots", "workers", "onboarding_done", "map_mode"}

    @app.get("/api/settings")
    def get_settings(user=viewer):
        s = db.settings()
        return {k: s.get(k) for k in EDITABLE}

    @app.put("/api/settings")
    def put_settings(body: dict, user=Depends(current_user)):
        values = {k: v for k, v in body.items() if k in EDITABLE}
        if set(values) - {"onboarding_done", "map_mode"} and not auth.role_at_least(user, "admin"):
            raise HTTPException(403, "Only an admin can change settings.")
        try:
            if "match_threshold" in values and not 0.25 <= float(values["match_threshold"]) <= 0.9:
                raise HTTPException(400, "Match threshold must be between 0.25 and 0.90.")
            if "analysis_fps" in values and not 0.2 <= float(values["analysis_fps"]) <= 15:
                raise HTTPException(400, "Analysis speed must be 0.2 to 15 frames per second.")
            if "retention_days" in values and not 1 <= int(values["retention_days"]) <= 3650:
                raise HTTPException(400, "Keep records for 1 to 3650 days.")
        except ValueError:
            raise HTTPException(400, "Please enter a number.")
        db.set_settings(values)
        sysm.invalidate_settings()
        if set(values) - {"onboarding_done", "map_mode"}:
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
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        sysm.stats["ui_loads"] = sysm.stats.get("ui_loads", 0) + 1
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app
