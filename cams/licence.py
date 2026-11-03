"""
CAMS licence client — drop this into the CAMS desktop app.

Checks the signed licence file OFFLINE, works out which features are unlocked,
and talks to the CAMS licence server when internet is available.

Golden rule: live view, recording and emergency alerts are NEVER switched off
because of payment. Only paid features lock.

Needs:  pip install cryptography requests
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
API_URL = "https://iezaqksdtuyiahtcfbzk.supabase.co/functions/v1/licence-api"

# Transit Tech's public signing key. CAMS can CHECK licence files with it, never make them.
PUBLIC_KEY_B64 = "9huIc3Kw6AF+d+7+xm3Tc/i8S454Mnof5nzNS3vdv1c="

ALWAYS_ON = {"live_view", "recording", "emergency_alerts"}
FREE_FEATURES = ["live_view", "recording", "clip_download", "emergency_alerts"]
FREE_MAX_CAMERAS = 2

APP_DIR = Path(os.getenv("APPDATA") or Path.home() / ".config") / "CAMS"
LICENCE_PATH = APP_DIR / "licence.cams"
CLOCK_PATH = APP_DIR / "clock.dat"
KEY_PATH = APP_DIR / "key.dat"


# ---------------------------------------------------------------------------
# Computer fingerprint (a hash, never personal data)
# ---------------------------------------------------------------------------
def device_fingerprint() -> str:
    parts = [platform.system(), platform.machine(), platform.node()]
    try:
        if platform.system() == "Windows":
            out = subprocess.run(
                ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            parts.append(out.strip().split()[-1])
        elif Path("/etc/machine-id").exists():
            parts.append(Path("/etc/machine-id").read_text().strip())
    except Exception:
        pass
    parts.append(hex(uuid.getnode()))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Licence result
# ---------------------------------------------------------------------------
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
    needs_online_check: bool = False
    message: str = ""

    def has(self, feature: str) -> bool:
        return feature in ALWAYS_ON or feature in self.features

    @property
    def banner(self) -> str | None:
        """Text for the banner at the top of CAMS, or None for no banner."""
        if self.state == "trial" and self.trial_ends_at:
            days = max(0, (self.trial_ends_at - _now()).days)
            return f"Trial: {days} days left"
        if self.state == "due_soon" and self.paid_until:
            return f"Your plan renews on {self.paid_until:%d %b %Y}. Pay now to avoid interruption."
        if self.state == "grace":
            return "Payment overdue. Please pay to keep face recognition and the map."
        if self.state == "limited":
            return "Recording is still on. Pay to unlock face recognition and the map."
        if self.needs_online_check:
            return "Connect to the internet once so CAMS can check your licence."
        return None


def free_status(message: str = "", state: str = "free", needs_online_check: bool = False) -> LicenceStatus:
    return LicenceStatus(state=state, plan="free", plan_name="Free", max_cameras=FREE_MAX_CAMERAS,
                         max_phones=0, features=list(FREE_FEATURES), message=message,
                         needs_online_check=needs_online_check)


# ---------------------------------------------------------------------------
# Offline check
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


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
    """Saves the latest time seen. True if the computer clock was moved back by over a day."""
    try:
        last = _parse(CLOCK_PATH.read_text().strip())
    except Exception:
        last = None
    if last and now < last.replace(microsecond=0) - _one_day():
        return True
    if not last or now > last:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CLOCK_PATH.write_text(now.isoformat())
    return False


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


def check_licence(licence_file: dict | None = None, now: datetime | None = None,
                  fingerprint: str | None = None, check_clock: bool = True) -> LicenceStatus:
    """Works fully offline. Call on start-up and once an hour."""
    now = now or _now()
    if licence_file is None:
        try:
            licence_file = json.loads(LICENCE_PATH.read_text())
        except Exception:
            return free_status()

    lic = verify_file(licence_file)
    if lic is None:
        return free_status("Licence file is damaged or was changed.", state="invalid")

    if lic.get("device") and fingerprint is not None:
        if lic["device"] != hashlib.sha256(("cams-fp:" + fingerprint).encode()).hexdigest():
            return free_status("This licence belongs to another computer.", state="invalid")

    if check_clock and _clock_moved_back(now):
        return free_status("The computer clock looks wrong. Connect to the internet to check.",
                           state="invalid", needs_online_check=True)

    valid_until = _parse(lic["valid_until"])
    paid_until = _parse(lic.get("paid_until"))
    grace_until = _parse(lic.get("grace_until"))
    trial_ends = _parse(lic.get("trial_ends_at"))

    # File too old (no renewal for 14 days) -> paid features lock, recording stays on.
    if now > valid_until:
        return free_status("CAMS has not checked its licence for 14 days.", state="limited",
                           needs_online_check=True)

    # Work out today's state from the dates in the file (they may have moved on since it was issued).
    if lic["state"] == "trial" and trial_ends and now < trial_ends:
        state = "trial"
    elif paid_until and now < paid_until:
        state = "due_soon" if (paid_until - now).days < 7 else "active"
    elif grace_until and now < grace_until:
        state = "grace"
    elif paid_until:
        return free_status(state="limited")
    else:
        return free_status()

    return LicenceStatus(
        state=state, plan=lic["plan"], plan_name=lic["plan_name"],
        max_cameras=lic["max_cameras"], max_phones=lic["max_phones"] or 0,
        features=lic["features"], paid_until=paid_until, grace_until=grace_until,
        trial_ends_at=trial_ends,
    )


# ---------------------------------------------------------------------------
# Online calls (only when internet is available)
# ---------------------------------------------------------------------------
class LicenceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _call(action: str, **body) -> dict:
    import requests
    try:
        r = requests.post(API_URL, json={"action": action, **body}, timeout=20)
    except requests.RequestException:
        raise LicenceError("offline", "No internet. Connect and try again.")
    data = r.json()
    if r.status_code >= 400:
        raise LicenceError(data.get("error", "error"), data.get("message") or data.get("error", "Error"))
    return data


def _save(result: dict, key: str | None = None) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LICENCE_PATH.write_text(json.dumps(result["licence_file"]))
    if key:
        KEY_PATH.write_text(key)


def saved_key() -> str | None:
    try:
        return KEY_PATH.read_text().strip()
    except Exception:
        return None


def _base(version: str) -> dict:
    return {"fingerprint": device_fingerprint(), "computer_name": platform.node(), "cams_version": version}


def start_trial(version: str = "0.1.0") -> LicenceStatus:
    res = _call("start_trial", **_base(version))
    _save(res, res["licence_key"])
    return check_licence()


def activate(key: str, version: str = "0.1.0") -> LicenceStatus:
    res = _call("activate", licence_key=key, **_base(version))
    _save(res, key)
    return check_licence()


def renew(version: str = "0.1.0") -> LicenceStatus:
    """Call quietly every 7 days (or when 'renew_after' has passed). Safe to fail offline."""
    key = saved_key()
    if not key:
        return check_licence()
    try:
        _save(_call("renew", licence_key=key, **_base(version)))
    except LicenceError:
        pass
    return check_licence()


def deactivate() -> str:
    res = _call("deactivate", licence_key=saved_key(), fingerprint=device_fingerprint())
    LICENCE_PATH.unlink(missing_ok=True)
    KEY_PATH.unlink(missing_ok=True)
    return res["message"]


def plans() -> list[dict]:
    return _call("plans")["plans"]


def start_payment(plan_code: str, months: int, phone: str) -> dict:
    """Sends the USSD push. Returns payment_id, amount_tzs, network, message."""
    return _call("start_payment", licence_key=saved_key(), fingerprint=device_fingerprint(),
                 plan_code=plan_code, months=months, phone=phone)


def payment_status(payment_id: str) -> str:
    """Poll every 5 seconds after start_payment. Returns pending, paid or failed."""
    res = _call("payment_status", licence_key=saved_key(), fingerprint=device_fingerprint(),
                payment_id=payment_id)
    if res["status"] == "paid":
        _save(res)
    return res["status"]
