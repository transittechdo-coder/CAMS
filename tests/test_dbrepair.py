"""CAMS 1.9: a database damaged by a power cut is repaired at start, and daily backups."""

import sqlite3
import time

from cams import dbrepair
from cams.db import Database


def _filled(path, people=300):
    db = Database(path)
    db.execute("INSERT INTO users(username, password_hash, role, created_at) VALUES ('boss', 'x', 'admin', 0)")
    for i in range(people):
        db.execute("INSERT INTO people(full_name, created_at) VALUES (?, ?)", (f"Person {i} " + "x" * 300, time.time()))
    db.set_settings({"lan_access": "1"})
    with db.conn() as c:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return db


def _damage(path, at=0.55, size=4096 * 3):
    data = bytearray(path.read_bytes())
    start = int(len(data) * at) // 4096 * 4096
    data[start:start + size] = b"\xde\xad\xbe\xef" * (size // 4)
    path.write_bytes(bytes(data))


def test_damaged_database_is_repaired_and_keeps_what_it_can(tmp_path):
    p = tmp_path / "cams.db"
    _filled(p)
    _damage(p)
    assert dbrepair.problem(p)                        # really damaged ("malformed")
    db = Database(p)                                  # must not raise
    rep = db.repair_report
    assert rep and rep["source"] == "repaired"
    assert rep["kept"]["users"] == 1
    assert 100 < rep["kept"]["people"] < 300          # most people saved, the damaged pages lost
    assert db.get_setting("lan_access") == "1"
    assert dbrepair.problem(p) is None
    assert list((tmp_path / "damaged").iterdir())     # the damaged file was kept, not deleted
    db.execute("INSERT INTO people(full_name, created_at) VALUES ('new', 0)")    # works normally again


def test_newest_backup_is_used_when_it_is_better(tmp_path):
    p = tmp_path / "cams.db"
    db = _filled(p, people=50)
    assert db.backup() is not None
    p.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200 + b"garbage" * 3000)   # header destroyed
    for s in ("-wal", "-shm"):
        (tmp_path / f"cams.db{s}").unlink(missing_ok=True)
    db2 = Database(p)
    assert db2.repair_report["source"] == "backup"
    assert db2.repair_report["kept"]["people"] == 50 and db2.repair_report["kept"]["users"] == 1


def test_backups_keep_only_seven(tmp_path):
    p = tmp_path / "cams.db"
    db = _filled(p, people=3)
    for i in range(9):
        out = db.backup()
        out.rename(out.with_name(f"cams-2026010{i}-000000.db"))
    db.backup()
    assert len(dbrepair.backups(tmp_path / "backups")) == 7


def test_healthy_database_is_left_alone(tmp_path):
    p = tmp_path / "cams.db"
    _filled(p, people=3)
    db = Database(p)
    assert db.repair_report is None and not (tmp_path / "damaged").exists()
    with sqlite3.connect(p) as c:
        assert c.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 3
