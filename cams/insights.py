"""Timelines, routines, habits, daily report and "Ask CAMS".

Everything here is worked out from what the cameras recorded (sightings and
the activity timeline). The written notes are produced on the PC from fixed
sentence patterns, so they are fast, private and always say where the facts
came from. They describe what cameras saw, never guesses about character:
"not seen in the dining hall" can also mean "no camera saw them there".
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .behaviour import BUILTIN, PURPOSES, guess_purpose

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ------------------------------------------------------------------ time helpers
def day_str(d: date | None = None) -> str:
    return (d or date.today()).isoformat()


def day_bounds(day: str) -> tuple[float, float]:
    d = datetime.strptime(day, "%Y-%m-%d")
    start = d.timestamp()
    return start, (d + timedelta(days=1)).timestamp()


def at(day: str, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.strptime(day, "%Y-%m-%d").replace(hour=h, minute=m).timestamp()


def hm(ts: float) -> str:
    t = datetime.fromtimestamp(ts)
    return t.strftime("%I:%M %p").lstrip("0")


def span(a: float, b: float) -> str:
    ta, tb = datetime.fromtimestamp(a), datetime.fromtimestamp(b)
    if ta.strftime("%p") == tb.strftime("%p"):
        return f"{ta.strftime('%I:%M').lstrip('0')}–{tb.strftime('%I:%M %p').lstrip('0')}"
    return f"{hm(a)}–{hm(b)}"


def minutes(sec: float) -> str:
    m = int(round(sec / 60))
    if m < 1:
        return "under a minute"
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


OPEN_PLACES = re.compile(r"gate|field|ground|pitch|court|entrance|outdoor|walkway|parking|yard|compound", re.I)


def inp(place: str) -> str:
    """'in the Library', 'at the Main gate'."""
    return f"{'at' if OPEN_PLACES.search(place or '') else 'in'} the {place}"


def first(name: str) -> str:
    return (name or "").split()[0] if name else "This person"


def _json(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except ValueError:
        return default


class Insights:
    def __init__(self, sysm):
        self.sysm = sysm
        self.db = sysm.db

    # ------------------------------------------------------------ vocabulary
    def labels(self) -> dict[str, str]:
        b = getattr(self.sysm, "behaviour", None)
        return b.labels() if b else dict(BUILTIN)

    def label(self, key: str) -> str:
        return self.labels().get(key, key)

    def areas(self) -> list[dict]:
        out = []
        for a in self.db.query("SELECT id, name, kind, purpose FROM buildings ORDER BY name"):
            a = dict(a)
            a["purpose"] = a.get("purpose") or guess_purpose(a["name"])
            out.append(a)
        return out

    def place_of(self, cam_id) -> tuple[int | None, str]:
        areas = self.sysm.camera_areas.get(cam_id) or []
        if areas:
            return areas[0]["id"], areas[0]["name"]
        return None, ""

    def cams_for_areas(self, area_ids: set) -> set:
        return {cid for cid, areas in self.sysm.camera_areas.items() if any(a["id"] in area_ids for a in areas)}

    # ------------------------------------------------------------ raw facts
    def visits(self, pid: int, a: float, b: float) -> list[dict]:
        """Where the person was: camera sightings and timeline entries, merged per place."""
        cams = {c["id"]: c["name"] for c in self.db.query("SELECT id, name FROM cameras")}
        raw = []
        for s in self.db.query("SELECT camera_id, camera_name, first_seen, last_seen FROM sightings "
                               "WHERE person_id = ? AND last_seen >= ? AND first_seen < ? ORDER BY first_seen", (pid, a, b)):
            aid, aname = self.place_of(s["camera_id"])
            raw.append((s["first_seen"], s["last_seen"], aid, aname or s["camera_name"] or cams.get(s["camera_id"], "a camera"), s["camera_id"]))
        for s in self.db.query("SELECT camera_id, camera_name, area_id, area_name, start_ts, end_ts FROM activity_log "
                               "WHERE person_id = ? AND end_ts >= ? AND start_ts < ? ORDER BY start_ts", (pid, a, b)):
            raw.append((s["start_ts"], s["end_ts"], s["area_id"], s["area_name"] or s["camera_name"], s["camera_id"]))
        raw.sort()
        out: list[dict] = []
        for s, e, aid, place, cam in raw:
            if out and out[-1]["place"] == place and s - out[-1]["end"] <= 300:
                out[-1]["end"] = max(out[-1]["end"], e)
                continue
            out.append({"start": s, "end": e, "area_id": aid, "place": place, "camera_id": cam})
        return out

    def timeline(self, pid: int, a: float, b: float) -> list[dict]:
        return self.db.query(
            "SELECT id, camera_id, camera_name, area_id, area_name, activity, source, confidence, start_ts, end_ts, samples, image_path, example_id "
            "FROM activity_log WHERE person_id = ? AND end_ts >= ? AND start_ts < ? ORDER BY start_ts", (pid, a, b))

    def doing_at(self, pid: int, ts: float, slack: float = 300) -> dict | None:
        """The timeline entry covering this moment, or the closest one within `slack` seconds."""
        rows = self.db.query("SELECT * FROM activity_log WHERE person_id = ? AND start_ts <= ? AND end_ts >= ?", (pid, ts + slack, ts - slack))
        if not rows:
            return None
        gap = lambda r: 0 if r["start_ts"] <= ts <= r["end_ts"] else min(abs(ts - r["start_ts"]), abs(ts - r["end_ts"]))
        return min(rows, key=lambda r: (gap(r), r["end_ts"] - r["start_ts"]))

    def seen_people(self, a: float, b: float) -> set:
        rows = self.db.query("SELECT DISTINCT person_id FROM sightings WHERE person_id IS NOT NULL AND last_seen >= ? AND first_seen < ?", (a, b))
        rows += self.db.query("SELECT DISTINCT person_id FROM activity_log WHERE end_ts >= ? AND start_ts < ?", (a, b))
        return {r["person_id"] for r in rows}

    def people(self) -> dict[int, dict]:
        return {p["id"]: p for p in self.db.query("SELECT id, full_name, person_code, category, group_name FROM people WHERE active = 1")}

    # ------------------------------------------------------------ routines
    def routine_rows(self) -> list[dict]:
        out = []
        for r in self.db.query("SELECT * FROM routines ORDER BY start, name"):
            r = dict(r)
            for k in ("days", "area_ids", "who_categories", "who_groups", "who_people"):
                r[k] = _json(r[k], [])
            out.append(r)
        return out

    def in_scope(self, r: dict, p: dict) -> bool:
        cats, groups, ids = r["who_categories"], r["who_groups"], r["who_people"]
        if not (cats or groups or ids):
            return True
        return p["category"] in cats or (p.get("group_name") or "") in groups or p["id"] in ids

    def routine_areas(self, r: dict) -> list[dict]:
        areas = self.areas()
        if r["area_ids"]:
            return [a for a in areas if a["id"] in r["area_ids"]]
        if r["purpose"]:
            return [a for a in areas if a["purpose"] == r["purpose"]]
        return []

    def place_words(self, r: dict) -> str:
        names = [a["name"] for a in self.routine_areas(r)]
        if not names:
            return PURPOSES.get(r["purpose"], "the expected place").split(" /")[0].lower()
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]

    def check_routine(self, r: dict, day: str, write: bool = True) -> list[dict]:
        """Who kept this routine on this day. Writes notes (and alerts) when write=True."""
        a, b = at(day, r["start"]), at(day, r["end"])
        if b <= a:
            b += 86400
        areas = self.routine_areas(r)
        area_ids = {x["id"] for x in areas}
        target_cams = self.cams_for_areas(area_ids)
        d0, d1 = day_bounds(day)
        seen_today = self.seen_people(d0, min(d1, b + 3600))
        people = self.people()
        where = self.place_words(r)
        window = span(a, b)
        results = []
        labels = self.labels()
        for pid in sorted(seen_today):
            p = people.get(pid)
            if not p or not self.in_scope(r, p):
                continue
            vis = self.visits(pid, a - 600, b)
            inside = [v for v in vis if (v["area_id"] in area_ids or v["camera_id"] in target_cams) and v["end"] >= a and v["start"] <= b]
            name = first(p["full_name"])
            acts = self.db.query("SELECT activity, start_ts, end_ts FROM activity_log WHERE person_id = ? AND end_ts >= ? AND start_ts <= ? "
                                 "AND (area_id IN (%s) OR camera_id IN (%s))" % (",".join(str(i) for i in area_ids) or "NULL",
                                                                                 ",".join(str(i) for i in target_cams) or "NULL"), (pid, a, b))
            if r["expect"] == "absent":
                if not inside:
                    continue
                v = inside[0]
                text = f"{name} was {inp(v['place'])} during {r['name']} ({window}), at {span(max(v['start'], a), min(v['end'], b))}. Nobody is expected there at that time."
                results.append({"person_id": pid, "kind": "out_of_place", "text": text, "time": v["start"]})
                continue
            if inside:
                arrive = max(a, min(v["start"] for v in inside))
                leave = min(b, max(v["end"] for v in inside))
                did = Counter()
                for x in acts:
                    did[x["activity"]] += min(x["end_ts"], b) - max(x["start_ts"], a)
                doing = ""
                if did:
                    top = [labels.get(k, k).lower() for k, _ in did.most_common(2)]
                    doing = " Seen " + " and ".join(top) + "."
                came_late = min(v["start"] for v in inside) > a + r["grace_min"] * 60
                if came_late:
                    text = f"{name} came late to {r['name']}: first seen {inp(inside[0]['place'])} at {hm(arrive)} ({int((arrive - a) // 60)} min after it started).{doing}"
                    results.append({"person_id": pid, "kind": "late", "text": text, "time": arrive})
                else:
                    text = f"{name} was at {r['name']} {inp(inside[0]['place'])} from {hm(arrive)} to {hm(leave)}.{doing}"
                    results.append({"person_id": pid, "kind": "attended", "text": text, "time": arrive})
                continue
            elsewhere = [v for v in vis if v["end"] >= a and v["start"] <= b]
            if elsewhere:
                v = max(elsewhere, key=lambda v: min(v["end"], b) - max(v["start"], a))
                act = self.doing_at(pid, max(v["start"], a) + 60)
                doing = f", {labels.get(act['activity'], act['activity']).lower()}" if act else ""
                text = (f"{name} did not go to the {where} during {r['name']} ({window}). "
                        f"{name} was seen {inp(v['place'])} at {span(max(v['start'], a), min(v['end'], b))}{doing}.")
            else:
                text = (f"{name} was not seen {inp(where)} during {r['name']} ({window}). "
                        f"No camera saw {name} at that time, so {name} may have been somewhere without a camera.")
            results.append({"person_id": pid, "kind": "missed", "text": text, "time": a})
        if write:
            self.db.execute("DELETE FROM person_notes WHERE day = ? AND routine_id = ?", (day, r["id"]))
            now = time.time()
            for x in results:
                self.db.execute("INSERT INTO person_notes(person_id, day, ts, kind, routine_id, text) VALUES (?,?,?,?,?,?)",
                                (x["person_id"], day, x["time"] or now, x["kind"], r["id"], x["text"]))
                if r["alert"] and x["kind"] in ("missed", "out_of_place"):
                    self.sysm._alert("routine", x["text"], x["person_id"], None, None)
            self.db.execute("UPDATE routines SET checked_day = ? WHERE id = ?", (day, r["id"]))
        return results

    def run_due(self, now: datetime | None = None) -> int:
        """Called every minute: check routines that have just finished today."""
        now = now or datetime.now()
        day = day_str(now.date())
        n = 0
        for r in self.routine_rows():
            if not r["enabled"] or r["checked_day"] == day:
                continue
            if r["days"] and now.weekday() not in r["days"]:
                continue
            end = at(day, r["end"])
            if at(day, r["end"]) <= at(day, r["start"]):
                continue  # overnight routines are checked the next morning by recheck
            if now.timestamp() >= end + 120:
                self.check_routine(r, day)
                n += 1
        summary_at = self.sysm.setting("daily_summary_time") or "20:30"
        if self.sysm.setting("summary_day") != day and now.strftime("%H:%M") >= summary_at:
            self.write_day_summaries(day)
            self.db.set_settings({"summary_day": day})
            self.sysm.invalidate_settings()
        return n

    # ------------------------------------------------------------ habits
    def habits(self, pid: int, days: int = 21, before: str | None = None) -> dict:
        end_day = datetime.strptime(before, "%Y-%m-%d").date() if before else date.today() + timedelta(days=1)
        start_day = end_day - timedelta(days=days)
        a, b = day_bounds(day_str(start_day))[0], day_bounds(day_str(end_day))[0]
        firsts, lasts, place_time, act_time = [], [], Counter(), Counter()
        present = 0
        d = start_day
        while d < end_day:
            d0, d1 = day_bounds(day_str(d))
            vis = self.visits(pid, d0, d1)
            if vis:
                present += 1
                fs = datetime.fromtimestamp(vis[0]["start"]); ls = datetime.fromtimestamp(max(v["end"] for v in vis))
                firsts.append(fs.hour * 60 + fs.minute); lasts.append(ls.hour * 60 + ls.minute)
                for v in vis:
                    place_time[v["place"]] += max(30, v["end"] - v["start"])
            d += timedelta(days=1)
        for r in self.db.query("SELECT activity, SUM(MAX(end_ts - start_ts, 20)) AS t FROM activity_log WHERE person_id = ? AND start_ts >= ? AND start_ts < ? GROUP BY activity",
                               (pid, a, b)):
            act_time[r["activity"]] = r["t"]
        routines = defaultdict(Counter)
        names = {r["id"]: r["name"] for r in self.routine_rows()}
        for n in self.db.query("SELECT routine_id, kind FROM person_notes WHERE person_id = ? AND routine_id IS NOT NULL AND day >= ? AND day < ?",
                               (pid, day_str(start_day), day_str(end_day))):
            if n["routine_id"] in names:
                routines[names[n["routine_id"]]][n["kind"]] += 1
        fmt = lambda m: datetime(2000, 1, 1, int(m) // 60, int(m) % 60).strftime("%I:%M %p").lstrip("0")
        out = {
            "days": days, "days_seen": present,
            "usual_arrival": fmt(statistics.median(firsts)) if firsts else None,
            "usual_arrival_min": statistics.median(firsts) if firsts else None,
            "usual_leaving": fmt(statistics.median(lasts)) if lasts else None,
            "places": [{"place": k, "share": round(v / max(1, sum(place_time.values())), 2)} for k, v in place_time.most_common(5)],
            "activities": [{"activity": k, "label": self.label(k), "minutes_per_day": round(v / 60 / max(1, present))} for k, v in act_time.most_common(6)],
            "routines": [{"routine": k, **c} for k, c in routines.items()],
        }
        out["sentences"] = self.habit_sentences(out)
        return out

    def habit_sentences(self, h: dict) -> list[str]:
        if not h["days_seen"]:
            return [f"Not seen by any camera in the last {h['days']} days, so there are no habits yet."]
        s = [f"Seen on {h['days_seen']} of the last {h['days']} days."]
        if h["usual_arrival"]:
            s.append(f"Usually first seen around {h['usual_arrival']} and last seen around {h['usual_leaving']}.")
        if h["places"]:
            s.append("Most time in: " + ", ".join(f"{p['place'] or 'unmapped cameras'} ({int(p['share'] * 100)}%)" for p in h["places"][:3]) + ".")
        if h["activities"]:
            s.append("Most often: " + ", ".join(f"{a['label'].lower()} (about {a['minutes_per_day']} min a day)" for a in h["activities"][:3]) + ".")
        for r in h["routines"]:
            total = sum(r.get(k, 0) for k in ("attended", "late", "missed", "out_of_place"))
            if not total:
                continue
            bits = [f"{r.get('attended', 0)} on time"]
            if r.get("late"):
                bits.append(f"{r['late']} late")
            if r.get("missed"):
                bits.append(f"{r['missed']} missed")
            if r.get("out_of_place"):
                bits.append(f"{r['out_of_place']} times out of place")
            s.append(f"{r['routine']}: " + ", ".join(bits) + f" (of {total}).")
        return s

    # ------------------------------------------------------------ day summary + changes
    def day_facts(self, pid: int, day: str) -> dict:
        d0, d1 = day_bounds(day)
        vis = self.visits(pid, d0, d1)
        tl = self.timeline(pid, d0, d1)
        places, acts = Counter(), Counter()
        for v in vis:
            places[v["place"]] += max(30, v["end"] - v["start"])
        for t in tl:
            acts[t["activity"]] += max(20, t["end_ts"] - t["start_ts"])
        return {"visits": vis, "timeline": tl, "places": places, "acts": acts,
                "first": vis[0] if vis else None, "last": max(vis, key=lambda v: v["end"]) if vis else None}

    def summary_text(self, p: dict, day: str, facts: dict | None = None) -> str:
        f = facts or self.day_facts(p["id"], day)
        name = first(p["full_name"])
        if not f["first"]:
            return f"{name} was not seen by any camera."
        s = f"{name} was first seen at {hm(f['first']['start'])} {inp(f['first']['place'])} and last seen at {hm(f['last']['end'])} {inp(f['last']['place'])}."
        if f["acts"]:
            s += " Mostly " + ", ".join(f"{self.label(k).lower()} ({minutes(v)})" for k, v in f["acts"].most_common(3)) + "."
        if len(f["places"]) > 1:
            s += " Places: " + ", ".join(f"{k} ({minutes(v)})" for k, v in f["places"].most_common(4)) + "."
        return s

    def changes(self, p: dict, day: str, facts: dict | None = None) -> list[str]:
        f = facts or self.day_facts(p["id"], day)
        h = self.habits(p["id"], 21, before=day)
        name = first(p["full_name"])
        out = []
        if h["days_seen"] < 3:
            return out
        if f["first"] and h["usual_arrival_min"] is not None:
            t = datetime.fromtimestamp(f["first"]["start"]); m = t.hour * 60 + t.minute
            if m - h["usual_arrival_min"] >= 30:
                out.append(f"{name} arrived later than usual: first seen at {hm(f['first']['start'])}, usually around {h['usual_arrival']}.")
            elif h["usual_arrival_min"] - m >= 45:
                out.append(f"{name} was seen much earlier than usual: {hm(f['first']['start'])}, usually around {h['usual_arrival']}.")
        usual_places = {x["place"] for x in h["places"]}
        known_before = {r["area_name"] for r in self.db.query(
            "SELECT DISTINCT area_name FROM activity_log WHERE person_id = ? AND start_ts < ? AND start_ts >= ?",
            (p["id"], day_bounds(day)[0], day_bounds(day)[0] - 21 * 86400))}
        for place in f["places"]:
            if place and place not in usual_places and place not in known_before and f["places"][place] >= 120:
                out.append(f"{name} spent {minutes(f['places'][place])} {inp(place)}, a place {name} has not been seen in for at least 3 weeks.")
        usual = {a["activity"]: a["minutes_per_day"] for a in h["activities"]}
        for act, sec in f["acts"].items():
            mins = sec / 60
            if mins >= 15 and mins > 2.5 * max(4, usual.get(act, 0)):
                out.append(f"{name} spent {minutes(sec)} {self.label(act).lower()}, much more than usual (about {usual.get(act, 0)} min a day).")
        # missed the same routine several times recently
        rows = self.db.query("SELECT routine_id, COUNT(*) AS n FROM person_notes WHERE person_id = ? AND kind = 'missed' AND day <= ? AND day > ? GROUP BY routine_id",
                             (p["id"], day, day_str(datetime.strptime(day, "%Y-%m-%d").date() - timedelta(days=7))))
        names = {r["id"]: r["name"] for r in self.routine_rows()}
        for r in rows:
            if r["n"] >= 3 and r["routine_id"] in names:
                out.append(f"{name} has missed {names[r['routine_id']]} {r['n']} times in the last 7 days.")
        return out

    def write_day_summaries(self, day: str) -> int:
        d0, d1 = day_bounds(day)
        people = self.people()
        seen = self.seen_people(d0, d1)
        self.db.execute("DELETE FROM person_notes WHERE day = ? AND kind IN ('summary', 'change', 'not_seen')", (day,))
        now = time.time()
        for pid in seen:
            p = people.get(pid)
            if not p:
                continue
            facts = self.day_facts(pid, day)
            self.db.execute("INSERT INTO person_notes(person_id, day, ts, kind, text) VALUES (?,?,?,?,?)",
                            (pid, day, now, "summary", self.summary_text(p, day, facts)))
            for c in self.changes(p, day, facts):
                self.db.execute("INSERT INTO person_notes(person_id, day, ts, kind, text) VALUES (?,?,?,?,?)", (pid, day, now, "change", c))
        return len(seen)

    def notes(self, pid: int, day: str) -> list[dict]:
        return self.db.query("SELECT id, kind, routine_id, text, ts FROM person_notes WHERE person_id = ? AND day = ? ORDER BY ts", (pid, day))

    # ------------------------------------------------------------ daily report
    def report(self, day: str, category: str = "", group: str = "", include_unseen: bool = False) -> dict:
        d0, d1 = day_bounds(day)
        people = self.people()
        seen = self.seen_people(d0, d1)
        rows = []
        notes = defaultdict(list)
        for n in self.db.query("SELECT person_id, kind, text, routine_id FROM person_notes WHERE day = ? ORDER BY ts", (day,)):
            notes[n["person_id"]].append(n)
        for pid, p in sorted(people.items(), key=lambda kv: kv[1]["full_name"].lower()):
            if category and p["category"] != category:
                continue
            if group and (p.get("group_name") or "") != group:
                continue
            if pid not in seen and not include_unseen:
                continue
            f = self.day_facts(pid, day)
            nn = notes.get(pid, [])
            rows.append({
                "person_id": pid, "name": p["full_name"], "code": p["person_code"], "category": p["category"], "group": p["group_name"],
                "first_seen": f["first"]["start"] if f["first"] else None, "last_seen": f["last"]["end"] if f["last"] else None,
                "places": [{"place": k, "minutes": round(v / 60)} for k, v in f["places"].most_common(4)],
                "activities": [{"activity": k, "label": self.label(k), "minutes": round(v / 60)} for k, v in f["acts"].most_common(4)],
                "attended": sum(1 for n in nn if n["kind"] == "attended"), "late": sum(1 for n in nn if n["kind"] == "late"),
                "missed": sum(1 for n in nn if n["kind"] == "missed"), "out_of_place": sum(1 for n in nn if n["kind"] == "out_of_place"),
                "notes": [n["text"] for n in nn if n["kind"] in ("missed", "late", "out_of_place", "change")],
                "summary": next((n["text"] for n in nn if n["kind"] == "summary"), None) or (self.summary_text(p, day, f) if f["first"] else "Not seen by any camera."),
            })
        return {"day": day, "people": rows, "seen": len(seen & set(people)), "enrolled": len(people),
                "missed": sum(r["missed"] for r in rows), "late": sum(r["late"] for r in rows), "out_of_place": sum(r["out_of_place"] for r in rows)}

    def report_csv(self, rep: dict) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Name", "ID", "Type", "Class / dept", "First seen", "Last seen", "Places", "Activities", "On time", "Late", "Missed", "Out of place", "Notes"])
        for r in rep["people"]:
            w.writerow([r["name"], r["code"], r["category"], r["group"],
                        hm(r["first_seen"]) if r["first_seen"] else "", hm(r["last_seen"]) if r["last_seen"] else "",
                        "; ".join(f"{p['place']} {p['minutes']} min" for p in r["places"]),
                        "; ".join(f"{a['label']} {a['minutes']} min" for a in r["activities"]),
                        r["attended"], r["late"], r["missed"], r["out_of_place"], " | ".join(r["notes"])])
        return buf.getvalue()

    # ------------------------------------------------------------ Ask CAMS
    ACT_WORDS = {
        "eating": ("eat", "ate", "eating", "food", "drink", "drinking", "meal"),
        "phone": ("phone", "mobile", "simu"),
        "running": ("run", "ran", "running"),
        "walking": ("walk", "walking", "walked"),
        "sitting": ("sit", "sat", "sitting", "seated"),
        "standing": ("stand", "standing", "stood"),
        "lying": ("lying", "lay", "lie down"),
        "sleeping": ("sleep", "slept", "sleeping", "resting", "rest"),
        "reading": ("read", "reading", "write", "writing", "studying", "study"),
        "computer": ("computer", "laptop"),
        "sport": ("sport", "football", "playing", "play", "ball", "game"),
        "hand_up": ("hand up", "raised", "raising"),
        "group": ("group", "chatting", "talking"),
    }

    def _when(self, q: str) -> tuple[str, float | None, tuple[float, float] | None]:
        """(day, exact moment or None, (from, to) or None) mentioned in the question."""
        today = date.today()
        d = today
        if "yesterday" in q or "jana" in q:
            d = today - timedelta(days=1)
        else:
            for i, n in enumerate(DAY_NAMES):
                if re.search(rf"\b(last\s+)?{n}\b", q):
                    back = (today.weekday() - i) % 7 or (7 if "last" in q else 0)
                    d = today - timedelta(days=back)
            m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", q) or re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", q)
            if m and "-" in m.group(0):
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif m:
                yy = int(m.group(3)) if m.group(3) else today.year
                yy = yy + 2000 if yy < 100 else yy
                try:
                    d = date(yy, int(m.group(2)), int(m.group(1)))
                except ValueError:
                    pass
        day = day_str(d)
        if re.search(r"\b(now|right now|currently|at the moment)\b", q) or re.search(r"\bwhere is\b|\bwho is in\b|\bwhat is .* doing\b", q):
            if d == today:
                return day, time.time(), None
        m = re.search(r"\b(?:at|around|by)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b", q)
        if m and (m.group(2) or m.group(3)) and not re.match(r"\d{1,2}/", q[m.start(1):]):
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            ap = (m.group(3) or "").replace(".", "")
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
            if 0 <= h < 24 and 0 <= mi < 60:
                return day, at(day, f"{h:02d}:{mi:02d}"), None
        for word, (h0, h1) in (("morning", ("06:00", "12:00")), ("afternoon", ("12:00", "17:00")), ("evening", ("17:00", "22:00")), ("night", ("19:00", "23:59"))):
            if word in q:
                return day, None, (at(day, h0), at(day, h1))
        return day, None, None

    def _find(self, q: str, items: list[tuple[str, object]]):
        best, best_len = None, 0
        for text, val in items:
            t = text.lower().strip()
            if len(t) >= 2 and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", q) and len(t) > best_len:
                best, best_len = val, len(t)
        return best

    def ask(self, question: str) -> dict:
        q = " " + re.sub(r"\s+", " ", question.lower().replace("?", " ").replace("’", "'")) + " "
        day, moment, window = self._when(q)
        d0, d1 = day_bounds(day)
        people = self.people()
        names = []
        for p in people.values():
            names.append((p["full_name"], p))
            parts = p["full_name"].split()
            if parts and len(parts[0]) >= 3 and sum(1 for x in people.values() if x["full_name"].split()[:1] == parts[:1]) == 1:
                names.append((parts[0], p))
            if p["person_code"]:
                names.append((p["person_code"], p))
        person = self._find(q, names)
        areas = self.areas()
        area_items = [(a["name"], a) for a in areas]
        for a in areas:
            if a["purpose"] == "dining":
                area_items += [("dining hall", a), ("dh", a), ("canteen", a)]
            if a["purpose"] == "library":
                area_items.append(("library", a))
            if a["purpose"] == "dormitory":
                area_items += [("dorm", a), ("dormitory", a), ("hostel", a)]
            if a["purpose"] == "sports":
                area_items += [("field", a), ("sports ground", a)]
        area = self._find(q, area_items)
        routines = self.routine_rows()
        routine = self._find(q, [(r["name"], r) for r in routines])
        act = None
        for key, words in self.ACT_WORDS.items():
            if any(re.search(rf"\b{re.escape(w)}\b", q) for w in words):
                act = key
                break
        custom = self._find(q, [(lbl, k) for k, lbl in self.labels().items() if k not in BUILTIN])
        act = custom or act
        when_words = f" on {datetime.strptime(day, '%Y-%m-%d').strftime('%A %d %B')}" if day != day_str() else " today"
        items: list[dict] = []

        def person_item(pid, detail, ts=None):
            p = people.get(pid)
            return {"person_id": pid, "name": p["full_name"] if p else f"#{pid}", "detail": detail, "time": ts}

        # --- about one person ------------------------------------------------
        if person and not re.search(r"\bwho\b", q):
            pid, name = person["id"], person["full_name"]
            if re.search(r"\bwhere\b", q):
                ts = moment
                if ts:
                    vis = [v for v in self.visits(pid, ts - 3600, ts + 900) if v["start"] <= ts + 300]
                    if vis:
                        v = vis[-1]
                        gap = ts - v["end"]
                        act_row = self.doing_at(pid, min(ts, v["end"]))
                        doing = f", {self.label(act_row['activity']).lower()}" if act_row else ""
                        if gap <= 300:
                            return {"answer": f"At {hm(ts)}, {name} was {inp(v['place'])}{doing}.", "items": [], "intent": "where"}
                        return {"answer": f"{name} was last seen before {hm(ts)} {inp(v['place'])} at {hm(v['end'])}{doing}.", "items": [], "intent": "where"}
                vis = self.visits(pid, d0 - 30 * 86400, min(d1, time.time() + 60))
                if vis:
                    v = vis[-1]
                    return {"answer": f"{name} was last seen {inp(v['place'])} at {hm(v['end'])} on {datetime.fromtimestamp(v['end']).strftime('%A %d %B')}.", "items": [], "intent": "where"}
                return {"answer": f"No camera has seen {name} recently.", "items": [], "intent": "where"}
            if re.search(r"\b(doing|did|activity|activities)\b", q) and (moment or window):
                ts = moment
                if ts:
                    row = self.doing_at(pid, ts)
                    if row:
                        place = row["area_name"] or row["camera_name"]
                        return {"answer": f"At {hm(ts)}{when_words if day != day_str() else ''}, {name} was {self.label(row['activity']).lower()}"
                                          f"{' in the ' + place if place else ''} (seen {span(row['start_ts'], row['end_ts'])}).", "items": [], "intent": "doing"}
                    return {"answer": f"CAMS has no record of what {name} was doing at {hm(ts)}. No camera recognised {name} then.", "items": [], "intent": "doing"}
                a, b = window
                tl = self.timeline(pid, a, b)
                if not tl:
                    return {"answer": f"No activity recorded for {name} in that time.", "items": [], "intent": "doing"}
                items = [person_item(pid, f"{self.label(t['activity'])}{' in ' + t['area_name'] if t['area_name'] else ''}", t["start_ts"]) for t in tl[:40]]
                return {"answer": f"What {name} was doing{when_words}:", "items": items, "intent": "doing"}
            # general: the day's story
            text = self.summary_text(person, day)
            notes = [n["text"] for n in self.notes(pid, day) if n["kind"] in ("missed", "late", "out_of_place", "change", "attended")]
            tl = self.timeline(pid, d0, d1)
            items = [person_item(pid, f"{self.label(t['activity'])}{' in ' + t['area_name'] if t['area_name'] else ''} ({span(t['start_ts'], t['end_ts'])})", t["start_ts"]) for t in tl[:60]]
            return {"answer": " ".join([text] + notes), "items": items, "intent": "person_day"}

        # --- who missed / was late -------------------------------------------
        if re.search(r"\b(miss|missed|skip|skipped|absent from|didn't go|did not go|didnt go|not go)\b", q):
            if routine:
                if not self.db.one("SELECT 1 FROM person_notes WHERE day = ? AND routine_id = ? LIMIT 1", (day, routine["id"])) \
                        and at(day, routine["end"]) < time.time():
                    self.check_routine(routine, day)
                rows = self.db.query("SELECT person_id, text FROM person_notes WHERE day = ? AND routine_id = ? AND kind = 'missed' ORDER BY ts", (day, routine["id"]))
                items = [person_item(r["person_id"], r["text"]) for r in rows]
                return {"answer": f"{len(items)} {'person' if len(items) == 1 else 'people'} missed {routine['name']}{when_words}." if items
                        else f"Nobody missed {routine['name']}{when_words} (of the people cameras saw that day).", "items": items, "intent": "missed"}
            rows = self.db.query("SELECT n.person_id, n.text FROM person_notes n WHERE n.day = ? AND n.kind = 'missed' ORDER BY n.ts", (day,))
            items = [person_item(r["person_id"], r["text"]) for r in rows]
            return {"answer": f"{len(items)} missed routine{'s' if len(items) != 1 else ''}{when_words}." if items else f"No missed routines recorded{when_words}.",
                    "items": items, "intent": "missed"}
        if re.search(r"\b(late|came late)\b", q):
            sql, args = "SELECT person_id, text FROM person_notes WHERE day = ? AND kind = 'late'", [day]
            if routine:
                sql += " AND routine_id = ?"; args.append(routine["id"])
            rows = self.db.query(sql + " ORDER BY ts", args)
            items = [person_item(r["person_id"], r["text"]) for r in rows]
            return {"answer": f"{len(items)} late{when_words}." if items else f"Nobody was recorded late{when_words}.", "items": items, "intent": "late"}
        if re.search(r"\b(not seen|absent|missing|didn't come|did not come)\b", q):
            seen = self.seen_people(d0, d1)
            items = [person_item(pid, f"{p['category']}{', ' + p['group_name'] if p['group_name'] else ''}") for pid, p in people.items() if pid not in seen]
            return {"answer": f"{len(items)} enrolled {'person was' if len(items) == 1 else 'people were'} not seen by any camera{when_words}.", "items": items, "intent": "not_seen"}

        # --- who did an activity ---------------------------------------------
        if act:
            a, b = (moment - 300, moment + 300) if moment else (window or (d0, d1))
            sql = "SELECT person_id, area_name, camera_name, start_ts, end_ts FROM activity_log WHERE activity = ? AND end_ts >= ? AND start_ts <= ?"
            args = [act, a, b]
            if area:
                sql += " AND area_id = ?"; args.append(area["id"])
            rows = self.db.query(sql + " ORDER BY start_ts", args)
            per = defaultdict(list)
            for r in rows:
                per[r["person_id"]].append(r)
            items = [person_item(pid, f"{self.label(act)} in {rs[0]['area_name'] or rs[0]['camera_name']} ({', '.join(span(r['start_ts'], r['end_ts']) for r in rs[:3])})", rs[0]["start_ts"])
                     for pid, rs in per.items()]
            where = f" {inp(area['name'])}" if area else ""
            t = f" at {hm(moment)}" if moment else ""
            return {"answer": f"{len(items)} {'person was' if len(items) == 1 else 'people were'} seen {self.label(act).lower()}{where}{t}{when_words}." if items
                    else f"Nobody was seen {self.label(act).lower()}{where}{t}{when_words}.", "items": items, "intent": "activity"}

        # --- who was in a place ----------------------------------------------
        if area:
            a, b = (moment - 300, moment + 300) if moment else (window or (d0, d1))
            cams = self.cams_for_areas({area["id"]})
            found = {}
            for pid in self.seen_people(a, b):
                vis = [v for v in self.visits(pid, a, b) if (v["area_id"] == area["id"] or v["camera_id"] in cams) and v["end"] >= a and v["start"] <= b]
                if vis:
                    found[pid] = vis
            items = [person_item(pid, ", ".join(span(v["start"], v["end"]) for v in vs[:3]), vs[0]["start"]) for pid, vs in found.items()]
            t = f" at {hm(moment)}" if moment else ""
            return {"answer": f"{len(items)} {'person was' if len(items) == 1 else 'people were'} {inp(area['name'])}{t}{when_words}.", "items": items, "intent": "in_place"}

        if routine:
            rows = self.db.query("SELECT person_id, kind, text FROM person_notes WHERE day = ? AND routine_id = ? ORDER BY kind, ts", (day, routine["id"]))
            items = [person_item(r["person_id"], r["text"]) for r in rows]
            return {"answer": f"{routine['name']}{when_words}: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in Counter(r['kind'] for r in rows).items()) if rows
                    else f"{routine['name']} has not been checked yet{when_words}.", "items": items, "intent": "routine"}

        return {"answer": "I could not understand that question. Try one of these:", "items": [], "intent": "help",
                "examples": ["Who missed lunch today?", "Where was Godwill at 8:00 AM?", "What was Godwill doing at 10:30 yesterday?",
                             "Who was in the library this afternoon?", "Who was using a phone today?", "Who was late for assembly?",
                             "Who was not seen today?", "Godwill today"]}
