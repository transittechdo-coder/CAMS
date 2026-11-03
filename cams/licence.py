"""CAMS licence: plans, free trial, licence keys and mobile-money payments.

The licence file is signed by the Transit Tech licence server and checked here
OFFLINE with the public key below, so CAMS works without internet. CAMS talks to
the server only to start a trial, activate a key, renew about once a week and pay.

Golden rule: live view, recording and emergency alerts are NEVER switched off
because of payment. Only paid features (more cameras, face enrolment ...) lock.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

log = logging.getLogger("cams.licence")

API_URL = os.environ.get("CAMS_LICENCE_URL", "https://iezaqksdtuyiahtcfbzk.supabase.co/functions/v1/licence-api")

# Transit Tech's public signing key. CAMS can CHECK licence files with it, never make them.
PUBLIC_KEY_B64 = "9huIc3Kw6AF+d+7+xm3Tc/i8S454Mnof5nzNS3vdv1c="

ALWAYS_ON = {"live_view", "recording", "emergency_alerts"}
FREE_FEATURES = ["live_view", "recording", "clip_download", "emergency_alerts"]
FREE_MAX_CAMERAS = 2

# What each paid feature is called on screen (used for "locked" messages and the plan table)
FEATURE_NAMES = {
    "live_view": "Live view", "recording": "Recording", "clip_download": "Download clips",
    "emergency_alerts": "Fire, smoke and person-down alarms", "motion_alerts": "Motion alerts",
    "clip_export": "Export video", "daily_report": "Daily report", "guard_app": "Guard phone app",
    "face_recognition": "Face recognition", "last_seen_search": "Find a person",
    "restricted_zones": "Restricted zones", "building_map": "2D / 3D campus map", "routes": "Routes with video",
    "visitor_checkin": "Visitor check-in", "number_plates": "Number plates", "bag_left_behind": "Bag left behind",
    "multi_site": "Several sites", "priority_support": "Priority support",
}

# Shown when CAMS is offline and has never fetched the price list
DEFAULT_PLANS = [
    {"code": "free", "name": "Free", "monthly_price_tzs": 0, "yearly_price_tzs": 0, "max_cameras": 2, "max_phones": 0,
     "features": FREE_FEATURES},
    {"code": "pro", "name": "Pro", "monthly_price_tzs": 50000, "yearly_price_tzs": 500000, "max_cameras": 6, "max_phones": 1,
     "features": FREE_FEATURES + ["motion_alerts", "clip_export", "daily_report", "guard_app"]},
    {"code": "premium", "name": "Premium", "monthly_price_tzs": 150000, "yearly_price_tzs": 1500000, "max_cameras": 16,
     "max_phones": 5, "features": FREE_FEATURES + ["motion_alerts", "clip_export", "daily_report", "guard_app",
                                                    "face_recognition", "last_seen_search", "restricted_zones",
                                                    "building_map", "routes", "visitor_checkin", "number_plates",
                                                    "bag_left_behind"]},
]


# ---------------------------------------------------------------------------
# Where the licence lives: the CAMS data folder (same as the database)
# ---------------------------------------------------------------------------
def data_dir() -> Path:
    from .config import _data_dir
    return _data_dir()


def _file(name: str) -> Path:
    return data_dir() / name


LICENCE_FILE = "licence.cams"
KEY_FILE = "licence.key"
CLOCK_FILE = "licence.clock"
PLANS_FILE = "licence.plans.json"


def enforced() -> bool:
    """Plan limits are checked unless CAMS_LICENCE_ENFORCE=0 (used by developers and old tests)."""
    return os.environ.get("CAMS_LICENCE_ENFORCE", "1") != "0"


# ---------------------------------------------------------------------------
# Computer fingerprint (a hash, never personal data)
# ---------------------------------------------------------------------------
_fp_cache: str | None = None


def device_fingerprint() -> str:
    global _fp_cache
    if _fp_cache:
        return _fp_cache
    parts = [platform.system(), platform.machine(), platform.node()]
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
                                 capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            parts.append(out.strip().split()[-1])
        elif Path("/etc/machine-id").exists():
            parts.append(Path("/etc/machine-id").read_text().strip())
    except Exception:
        pass
    parts.append(hex(uuid.getnode()))
    _fp_cache = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return _fp_cache


# ---------------------------------------------------------------------------
# Licence result
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


@dataclass
class LicenceStatus:
    state: str                      # trial, active, due_soon, grace, limited, free, invalid
    plan: str
    plan_name: str
    max_cameras: int | None
    max_phones: int
    features: list[str] = field(default_factory=list)
    paid_until: datetime | None = None
    grace_until: datetime | None = None
    trial_ends_at: datetime | None = None
    paid_plan: str | None = None
    renew_after: datetime | None = None
    needs_online_check: bool = False
    message: str = ""

    def has(self, feature: str) -> bool:
        return feature in ALWAYS_ON or feature in self.features

    @property
    def banner(self) -> str | None:
        """Text for the bar at the top of CAMS, or None for no bar."""
        if self.state == "trial" and self.trial_ends_at:
            days = max(0, (self.trial_ends_at - _now()).days)
            return f"Premium trial: {days} day{'s' if days != 1 else ''} left. Choose a plan to keep face recognition and the map."
        if self.state == "due_soon" and self.paid_until:
            return f"Your {self.plan_name} plan ends on {self.paid_until.astimezone():%d %b %Y}. Pay now to avoid interruption."
        if self.state == "grace":
            return "Payment is overdue. Pay soon to keep your paid features. Recording keeps working."
        if self.state == "limited":
            return "Recording is still on. Pay to unlock your paid features again."
        if self.state == "invalid" and self.message:
            return self.message
        if self.needs_online_check:
            return "Connect to the internet once so CAMS can check its licence."
        return None

    def to_dict(self) -> dict:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {
            "state": self.state, "plan": self.plan, "plan_name": self.plan_name, "paid_plan": self.paid_plan,
            "max_cameras": self.max_cameras, "max_phones": self.max_phones, "features": self.features,
            "paid_until": iso(self.paid_until), "grace_until": iso(self.grace_until),
            "trial_ends_at": iso(self.trial_ends_at), "needs_online_check": self.needs_online_check,
            "message": self.message, "banner": self.banner,
        }


def free_status(message: str = "", state: str = "free", needs_online_check: bool = False) -> LicenceStatus:
    return LicenceStatus(state=state, plan="free", plan_name="Free", max_cameras=FREE_MAX_CAMERAS,
                         max_phones=0, features=list(FREE_FEATURES), message=message,
                         needs_online_check=needs_online_check)


# ---------------------------------------------------------------------------
# Offline check
# ---------------------------------------------------------------------------
def verify_file(licence_file: dict, public_key_b64: str = PUBLIC_KEY_B64) -> dict | None:
    """Returns the licence data if the signature is genuine, else None."""
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        data = licence_file["data"]
        key.verify(base64.b64decode(licence_file["sig"]), data.encode())
        return json.loads(base64.b64decode(data))
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return None


def _clock_moved_back(now: datetime) -> bool:
    """Saves the latest time seen. True if the computer clock was moved back by more than a day."""
    p = _file(CLOCK_FILE)
    try:
        last = _parse(p.read_text().strip())
    except Exception:
        last = None
    if last and now < last - timedelta(days=1):
        return True
    if not last or now > last:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(now.isoformat())
        except OSError:
            pass
    return False


def load_file() -> dict | None:
    try:
        return json.loads(_file(LICENCE_FILE).read_text())
    except Exception:
        return None


def check_licence(licence_file: dict | None = None, now: datetime | None = None,
                  fingerprint: str | None = None, check_clock: bool = True) -> LicenceStatus:
    """Works fully offline. Cheap: call it whenever a feature needs checking."""
    now = now or _now()
    if licence_file is None:
        licence_file = load_file()
        if licence_file is None:
            return free_status()
        if fingerprint is None:
            fingerprint = device_fingerprint()

    lic = verify_file(licence_file)
    if lic is None:
        return free_status("The licence file is damaged or was changed. Enter your key again.", state="invalid")

    if lic.get("device") and fingerprint is not None:
        if lic["device"] != hashlib.sha256(("cams-fp:" + fingerprint).encode()).hexdigest():
            return free_status("This licence belongs to another computer. Enter your key to move it here.", state="invalid")

    if check_clock and _clock_moved_back(now):
        return free_status("The computer clock looks wrong. Connect to the internet so CAMS can check the date.",
                           state="invalid", needs_online_check=True)

    valid_until = _parse(lic["valid_until"])
    paid_until = _parse(lic.get("paid_until"))
    grace_until = _parse(lic.get("grace_until"))
    trial_ends = _parse(lic.get("trial_ends_at"))
    renew_after = _parse(lic.get("renew_after"))

    # File too old (not renewed for 14 days): paid features lock, recording stays on.
    if now > valid_until:
        s = free_status("CAMS has not checked its licence for 14 days.", state="limited", needs_online_check=True)
        s.paid_plan = lic.get("paid_plan")
        return s

    # Today's state from the dates in the file (they may have moved on since it was issued).
    if lic["state"] == "trial" and trial_ends and now < trial_ends:
        state = "trial"
    elif paid_until and now < paid_until:
        state = "due_soon" if paid_until - now < timedelta(days=7) else "active"
    elif grace_until and now < grace_until:
        state = "grace"
    elif paid_until:
        s = free_status(state="limited")
        s.paid_plan, s.paid_until, s.grace_until = lic.get("paid_plan"), paid_until, grace_until
        return s
    else:
        s = free_status()
        s.trial_ends_at = trial_ends
        return s

    return LicenceStatus(
        state=state, plan=lic["plan"], plan_name=lic["plan_name"],
        max_cameras=lic["max_cameras"], max_phones=lic["max_phones"] or 0,
        features=lic["features"], paid_until=paid_until, grace_until=grace_until,
        trial_ends_at=trial_ends, paid_plan=lic.get("paid_plan"), renew_after=renew_after,
    )


def current() -> LicenceStatus:
    return check_licence()


def feature_locked_message(feature: str) -> str:
    name = FEATURE_NAMES.get(feature, feature.replace("_", " "))
    need = next((p["name"] for p in DEFAULT_PLANS if feature in p["features"]), "a paid")
    return f"{name} needs the {need} plan. Open Licence & billing to start a free trial or upgrade."


# ---------------------------------------------------------------------------
# Online calls (only when internet is available)
# ---------------------------------------------------------------------------
class LicenceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _call(action: str, timeout: float = 20, **body) -> dict:
    req = urllib.request.Request(API_URL, data=json.dumps({"action": action, **body}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "CAMS"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode() or "{}")
        except Exception:
            data = {}
        raise LicenceError(data.get("error", "error"), data.get("message") or data.get("error") or f"Error {e.code}", e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LicenceError("offline", "No internet. Connect this computer to the internet and try again.", 503)


def _save(result: dict, key: str | None = None) -> None:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    _file(LICENCE_FILE).write_text(json.dumps(result["licence_file"]))
    if key:
        _file(KEY_FILE).write_text(key)


def saved_key() -> str | None:
    try:
        return _file(KEY_FILE).read_text().strip() or None
    except Exception:
        return None


def key_hint() -> str | None:
    k = saved_key()
    return f"CAMS-••••-••••-••••-{k[-4:]}" if k else None


def _base(version: str) -> dict:
    return {"fingerprint": device_fingerprint(), "computer_name": platform.node(), "cams_version": version}


def start_trial(version: str) -> LicenceStatus:
    res = _call("start_trial", **_base(version))
    _save(res, res["licence_key"])
    return check_licence()


def activate(key: str, version: str) -> LicenceStatus:
    key = key.strip().upper()
    res = _call("activate", licence_key=key, **_base(version))
    _save(res, key)
    return check_licence()


def renew(version: str) -> LicenceStatus:
    """Gets a fresh licence file. Raises LicenceError when offline."""
    key = saved_key()
    if not key:
        return check_licence()
    _save(_call("renew", licence_key=key, **_base(version)))
    return check_licence()


def deactivate() -> str:
    key = saved_key()
    if not key:
        raise LicenceError("no_key", "There is no licence key on this computer.")
    res = _call("deactivate", licence_key=key, fingerprint=device_fingerprint())
    for f in (LICENCE_FILE, KEY_FILE):
        try:
            _file(f).unlink()
        except FileNotFoundError:
            pass
    return res["message"]


def plans() -> list[dict]:
    """Price list from the server; the last copy (or the built-in one) when offline."""
    try:
        data = _call("plans", timeout=8)["plans"]
        try:
            _file(PLANS_FILE).write_text(json.dumps(data))
        except OSError:
            pass
        return data
    except LicenceError:
        try:
            return json.loads(_file(PLANS_FILE).read_text())
        except Exception:
            return DEFAULT_PLANS


def start_payment(plan_code: str, months: int, phone: str) -> dict:
    """Sends the USSD prompt to the customer's phone. Returns payment_id, amount_tzs, network, message."""
    key = saved_key()
    if not key:
        raise LicenceError("no_key", "Start the free trial or enter a licence key first.")
    return _call("start_payment", licence_key=key, fingerprint=device_fingerprint(),
                 plan_code=plan_code, months=months, phone=phone)


def payment_status(payment_id: str) -> dict:
    """Poll every 5 seconds after start_payment. Returns {status: pending|paid|failed, ...}."""
    res = _call("payment_status", licence_key=saved_key(), fingerprint=device_fingerprint(), payment_id=payment_id)
    if res.get("status") == "paid":
        _save(res)
    return {"status": res["status"], "receipt_no": res.get("receipt_no")}


# ---------------------------------------------------------------------------
# Quiet weekly renewal (called from the CAMS maintenance loop)
# ---------------------------------------------------------------------------
_renew_lock = threading.Lock()
_last_try = 0.0


def renew_if_due(version: str, now: float | None = None) -> None:
    """Renews in the background when the file asks for it; tries again every 6 hours when offline."""
    global _last_try
    now = now or time.time()
    if not saved_key() or now - _last_try < 6 * 3600:
        return
    s = check_licence()
    due = s.renew_after is None or s.needs_online_check or s.renew_after.timestamp() <= now
    if not due or not _renew_lock.acquire(blocking=False):
        return
    _last_try = now

    def run():
        try:
            renew(version)
            log.info("Licence renewed")
        except LicenceError as e:
            log.info("Licence renewal skipped: %s", e)
        except Exception:
            log.exception("Licence renewal failed")
        finally:
            _renew_lock.release()

    threading.Thread(target=run, name="licence-renew", daemon=True).start()
