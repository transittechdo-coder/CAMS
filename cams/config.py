"""Paths and runtime settings.

User data (database, face snapshots, map images) lives outside the program
folder so that reinstalling or upgrading CAMS never deletes it:

* Windows: %APPDATA%\\CAMS
* macOS / Linux: ~/.cams

Set the CAMS_DATA_DIR environment variable to override (used by the tests).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _base_dir() -> Path:
    """Folder holding the bundled program files (static UI, models)."""
    if getattr(sys, "frozen", False):  # running from the PyInstaller .exe
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    override = os.environ.get("CAMS_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "CAMS"
    return Path.home() / ".cams"


@dataclass(frozen=True)
class Paths:
    base: Path
    data: Path

    @property
    def static(self) -> Path:
        if getattr(sys, "frozen", False):
            return self.base / "cams" / "static"
        return self.base / "cams" / "static"

    @property
    def models(self) -> Path:
        override = os.environ.get("CAMS_MODELS_DIR")
        return Path(override) if override else self.base / "models"

    @property
    def db_file(self) -> Path:
        return self.data / "cams.db"

    @property
    def snapshots(self) -> Path:
        return self.data / "snapshots"

    @property
    def enrollments(self) -> Path:
        return self.data / "enrollments"

    @property
    def maps(self) -> Path:
        return self.data / "maps"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    def ensure(self) -> None:
        for p in (self.data, self.snapshots, self.enrollments, self.maps, self.logs):
            p.mkdir(parents=True, exist_ok=True)


def get_paths() -> Paths:
    return Paths(base=_base_dir(), data=_data_dir())


# Default values for settings stored in the database (settings table).
DEFAULT_SETTINGS: dict[str, str] = {
    "site_name": "My Campus",
    # Cosine similarity needed to accept a match. 0.363 is the threshold
    # published with the SFace model; we start slightly stricter.
    "match_threshold": "0.40",
    # How many frames per second each camera is analysed at.
    "analysis_fps": "2",
    # Seconds; a person seen again on the same camera within this window
    # extends the existing sighting instead of creating a new one.
    "sighting_merge_seconds": "20",
    # Days to keep sightings and their snapshots before automatic deletion.
    "retention_days": "30",
    # Blur faces of people who are not enrolled in live view and snapshots.
    "blur_unknown": "1",
    # Save a small face snapshot with each sighting.
    "save_snapshots": "1",
    # Number of recognition worker threads (0 = automatic).
    "workers": "0",
    # Activity AI: follow what each recognised person is doing (1 = on).
    "activity_ai": "1",
    # When the daily summary and "changes from usual" notes are written.
    "daily_summary_time": "20:30",
    "onboarding_done": "0",
    "map_mode": "2d",
}

SFACE_RECOMMENDED_THRESHOLD = 0.363
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("CAMS_PORT", "8765"))
