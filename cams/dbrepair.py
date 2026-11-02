"""Keeping the CAMS database safe: automatic backups and repair after a power cut.

If the power goes off while CAMS is writing, the database file (cams.db) can be damaged
("database disk image is malformed"). Then, when CAMS starts:

1. The damaged files are moved to  <data>/damaged/<date-time>/  (nothing is deleted).
2. A new, empty database is made, and every row that can still be read from the damaged
   one is copied into it - table by table, and row by row around the damaged places.
3. If that saved less than the newest automatic backup (for example no user accounts),
   the backup is used instead.
4. CAMS starts normally and shows an alert saying what happened and what was saved.

CAMS also makes a backup copy of the database every day (and at each start), keeping the
last 7, in  <data>/backups/ .
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("cams.db")

KEEP_BACKUPS = 7
CHUNK = 500
IMPORTANT = ("users", "people", "face_samples", "cameras", "buildings")


def problem(path: Path) -> str | None:
    """None if the database is healthy, else what is wrong."""
    if not Path(path).exists():
        return None
    try:
        c = sqlite3.connect(path, timeout=30)
        try:
            r = c.execute("PRAGMA quick_check").fetchall()
        finally:
            c.close()
        msg = "; ".join(str(x[0]) for x in r[:5])
        return None if msg == "ok" else msg
    except sqlite3.DatabaseError as exc:
        return str(exc)


def move_aside(path: Path) -> Path:
    """Move cams.db (and its -wal / -shm files) to data/damaged/<time>/ and return that folder."""
    folder = Path(path).parent / "damaged" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm", "-journal"):
        f = Path(str(path) + suffix)
        if f.exists():
            shutil.move(str(f), str(folder / f.name))
    return folder


def _readable_rows(src: sqlite3.Connection, table: str, cols: list[str]):
    """Every row of `table` that can still be read, going round damaged places."""
    sel = ", ".join(f'"{c}"' for c in cols)
    try:
        lo, hi = src.execute(f'SELECT MIN(rowid), MAX(rowid) FROM "{table}"').fetchone()
    except sqlite3.DatabaseError:
        lo, hi = None, None
    if lo is None:
        try:                                            # no row numbers readable: try all at once
            yield from src.execute(f'SELECT {sel} FROM "{table}"').fetchall()
        except sqlite3.DatabaseError:
            return
        return
    start = lo
    while start <= hi:
        end = start + CHUNK - 1
        try:
            yield from src.execute(f'SELECT {sel} FROM "{table}" WHERE rowid BETWEEN ? AND ?', (start, end)).fetchall()
        except sqlite3.DatabaseError:
            for rid in range(start, end + 1):           # damaged chunk: one row at a time
                try:
                    yield from src.execute(f'SELECT {sel} FROM "{table}" WHERE rowid = ?', (rid,)).fetchall()
                except sqlite3.DatabaseError:
                    continue
        start = end + 1


def salvage(damaged: Path, target: sqlite3.Connection) -> dict[str, int]:
    """Copy every readable row from the damaged file into `target` (which already has the tables)."""
    counts: dict[str, int] = {}
    try:
        src = sqlite3.connect(f"file:{damaged}?mode=ro", uri=True, timeout=30)
    except sqlite3.DatabaseError as exc:
        log.error("Cannot open the damaged database at all: %s", exc)
        return counts
    try:
        tables = [r[0] for r in target.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        target.execute("PRAGMA foreign_keys = OFF")
        for t in tables:
            new_cols = [r[1] for r in target.execute(f'PRAGMA table_info("{t}")')]
            try:
                old_cols = [r[1] for r in src.execute(f'PRAGMA table_info("{t}")')]
            except sqlite3.DatabaseError:
                old_cols = new_cols
            cols = [c for c in new_cols if c in old_cols]
            if not cols:
                continue
            ins = f'INSERT OR IGNORE INTO "{t}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({", ".join("?" * len(cols))})'
            if t in ("settings", "meta"):
                ins = ins.replace("INSERT OR IGNORE", "INSERT OR REPLACE")
            n = 0
            for row in _readable_rows(src, t, cols):
                try:
                    target.execute(ins, tuple(row))
                    n += 1
                except sqlite3.DatabaseError:
                    continue
            counts[t] = n
        target.commit()
        target.execute("PRAGMA foreign_keys = ON")
    finally:
        src.close()
    return counts


def backups(folder: Path) -> list[Path]:
    return sorted(Path(folder).glob("cams-*.db"), reverse=True) if Path(folder).exists() else []


def make_backup(path: Path, folder: Path, keep: int = KEEP_BACKUPS) -> Path | None:
    """A consistent copy of the live database (SQLite's own backup, safe while CAMS runs)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"cams-{time.strftime('%Y%m%d-%H%M%S')}.db"
    tmp = out.with_suffix(".part")
    try:
        src = sqlite3.connect(path, timeout=30)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        if problem(tmp):
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(out)
    except sqlite3.DatabaseError as exc:
        log.warning("Database backup failed: %s", exc)
        tmp.unlink(missing_ok=True)
        return None
    for old in backups(folder)[keep:]:
        old.unlink(missing_ok=True)
    return out


def count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except sqlite3.DatabaseError:
        return 0
