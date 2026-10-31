"""Keeping CAMS running through power cuts, and the System health page.

* **Start with Windows.** CAMS can start by itself when the PC is turned on (after a
  power cut too, if the PC is set to turn on when power returns).
* **How long was CAMS off?** CAMS notes the time every minute. When it starts and finds
  that it stopped without being closed properly (power cut, crash, PC turned off), it
  writes an alert with the time it was off, so the guard knows there is a gap in the
  recordings. Every gap is listed on the System health page.
* **Running on battery.** On a laptop, or a PC on a UPS that tells Windows its battery
  level, CAMS raises an alert when the power goes off and says how long the battery lasts.
* **System health.** One page with every camera's state, the disk, the AI, the battery
  and the computer's load.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .system import CamsSystem

log = logging.getLogger("cams.health")

HEARTBEAT_S = 60
GAP_ALERT_S = 180            # off for longer than this = a gap worth telling the guard about
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CAMS"


def _psutil():
    try:
        import psutil
        return psutil
    except Exception:  # pragma: no cover - optional
        return None


def fmt_span(sec: float) -> str:
    sec = int(sec)
    if sec < 3600:
        return f"{max(1, sec // 60)} min"
    h, m = divmod(sec // 60, 60)
    if h < 48:
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{h // 24} days {h % 24} h"


# ------------------------------------------------------------------ start with Windows
def _exe_command() -> str | None:
    if not getattr(sys, "frozen", False):
        return None                       # only the installed program can start with Windows
    return f'"{sys.executable}" --startup'


def _startup_shortcut() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "CAMS.lnk"


def autostart_state() -> dict:
    """{"supported", "on"}: on when the Run entry or the installer's Startup shortcut exists."""
    if not sys.platform.startswith("win"):
        return {"supported": False, "on": False}
    on = False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            on = True
    except OSError:
        pass
    sc = _startup_shortcut()
    if sc and sc.exists():
        on = True
    return {"supported": _exe_command() is not None, "on": on}


def set_autostart(on: bool) -> dict:
    if not sys.platform.startswith("win"):
        raise RuntimeError("Starting with the computer is only for Windows.")
    import winreg
    cmd = _exe_command()
    if on:
        if not cmd:
            raise RuntimeError("Only the installed CAMS can start with Windows.")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:     # no administrator needed
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, cmd)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, RUN_NAME)
        except OSError:
            pass
        sc = _startup_shortcut()
        if sc and sc.exists():
            sc.unlink()
    return autostart_state()


# ------------------------------------------------------------------ the monitor
class Health:
    def __init__(self, system: "CamsSystem"):
        self.sys = system
        self.db = system.db
        self.started_at = time.time()
        self._on_battery = False
        self._battery_low_sent = False
        self._last_beat = 0.0

    # called once when CAMS starts
    def on_start(self) -> dict | None:
        """Notice an unexpected stop (power cut) since last time; returns the gap if there was one."""
        s = self.db.settings()
        last = float(s.get("heartbeat") or 0)
        clean = s.get("clean_stop") == "1"
        now = time.time()
        gap = None
        if last and not clean and now - last > GAP_ALERT_S:
            gap = {"start": last, "end": now, "seconds": now - last}
            self.db.execute("INSERT INTO downtime(start_ts, end_ts, reason) VALUES (?, ?, ?)", (last, now, "unexpected"))
            when = time.strftime("%d %b %H:%M", time.localtime(last))
            back = time.strftime("%H:%M", time.localtime(now))
            self.sys._alert("downtime", f"CAMS was off for {fmt_span(now - last)} (from {when} to {back}): a power cut, "
                                        "or the computer was turned off. Nothing was recorded in that time.", None, None, None)
        elif last and clean and now - last > GAP_ALERT_S:
            self.db.execute("INSERT INTO downtime(start_ts, end_ts, reason) VALUES (?, ?, ?)", (last, now, "closed"))
        self.db.set_settings({"clean_stop": "0", "heartbeat": now})
        self._last_beat = now
        return gap

    def on_stop(self) -> None:
        self.db.set_settings({"clean_stop": "1", "heartbeat": time.time()})

    # called by the maintenance loop every 10 seconds
    def tick(self, now: float | None = None) -> None:
        now = now or time.time()
        if now - self._last_beat >= HEARTBEAT_S:
            self._last_beat = now
            self.db.set_settings({"heartbeat": now})
        self.check_battery()

    def battery(self) -> dict | None:
        ps = _psutil()
        if not ps or not hasattr(ps, "sensors_battery"):
            return None
        try:
            b = ps.sensors_battery()
        except Exception:
            return None
        if b is None:
            return None
        left = b.secsleft if isinstance(b.secsleft, (int, float)) and b.secsleft > 0 else None
        return {"percent": round(b.percent), "plugged": bool(b.power_plugged), "seconds_left": left}

    def check_battery(self, b: dict | None = None) -> None:
        b = b if b is not None else self.battery()
        if not b:
            return
        if not b["plugged"] and not self._on_battery:
            self._on_battery = True
            left = f", about {fmt_span(b['seconds_left'])} left" if b["seconds_left"] else ""
            self.sys._alert("power", f"Power cut: CAMS is running on battery ({b['percent']}%{left}). "
                                     "Save work and check the power or the generator.", None, None, None)
        elif not b["plugged"] and b["percent"] <= 15 and not self._battery_low_sent:
            self._battery_low_sent = True
            self.sys._alert("power", f"Battery almost empty ({b['percent']}%): CAMS will stop soon.", None, None, None)
        elif b["plugged"] and self._on_battery:
            self._on_battery = False
            self._battery_low_sent = False
            self.sys._alert("power", "Power is back: CAMS is no longer on battery.", None, None, None)

    # ------------------------------------------------------------------ the page
    def report(self) -> dict:
        import shutil

        s = self.sys
        now = time.time()
        cams = []
        for c in s.db.query("SELECT id, name, enabled, record_mode FROM cameras ORDER BY name"):
            st = s.camera_status(c["id"]) if c["enabled"] else {"status": "off"}
            w = s.cameras.get(c["id"])
            last = w.state.last_frame_at if w else 0
            off_since = w.state.offline_since if w else None
            last_rec = s.db.one("SELECT MAX(end_ts) AS t FROM recordings WHERE camera_id = ? AND kind != 'clip'", (c["id"],))
            cams.append({"id": c["id"], "name": c["name"], "status": st.get("status", "off"),
                         "fps": round(st.get("fps") or 0, 1), "error": st.get("error", ""),
                         "last_picture_ago": round(now - last) if last else None,
                         "offline_for": round(now - off_since) if off_since else None,
                         "recording": bool(s.recorder.active().get(c["id"])), "record_mode": c["record_mode"],
                         "last_recording": last_rec and last_rec["t"]})
        try:
            du = shutil.disk_usage(s.paths.data)
            disk = {"free": du.free, "total": du.total}
        except OSError:
            disk = None
        ps = _psutil()
        load = None
        if ps:
            try:
                load = {"cpu": ps.cpu_percent(interval=None), "ram": ps.virtual_memory().percent,
                        "cams_ram_mb": round(ps.Process().memory_info().rss / 1e6)}
            except Exception:
                load = None
        gaps = s.db.query("SELECT start_ts, end_ts, reason FROM downtime ORDER BY start_ts DESC LIMIT 20")
        last_backup = s.db.get_setting("last_backup", "") or None
        return {
            "now": now, "started_at": self.started_at, "uptime": round(now - self.started_at),
            "cameras": cams, "disk": disk, "load": load, "battery": self.battery(),
            "ai": {"faces": s.models_ok, "people": s.activity_ok, "pose": bool(s.behaviour and s.behaviour.pose_ok),
                   "plates": bool(getattr(s, "plates", None) and s.plates.available)},
            "autostart": autostart_state(), "downtime": gaps, "last_backup": last_backup,
            "frames_analysed": s.stats.get("frames_analysed", 0),
        }
