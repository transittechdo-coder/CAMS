"""Real-world position of the campus map, and satellite pictures.

The campus map is measured in metres: x to the right (east), y down (south),
(0, 0) at the top-left corner. Once the admin tells CAMS where the campus is
on Earth (the latitude and longitude of the map centre), every point on the
map has an exact GPS position, and CAMS can fetch a real satellite picture of
the compound to draw over.

Satellite tiles come from Esri World Imagery (internet needed once). Every
tile is kept in %APPDATA%\\CAMS\\tiles, and the finished picture is saved as
the map picture, so after that CAMS works fully offline again.

Maths: Web Mercator ("slippy map") pixels. Mercator keeps shapes, so across a
campus one metre is the same number of pixels in every direction; the scale at
the map centre's latitude is used for the whole map.
"""

from __future__ import annotations

import json
import math
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

TILE = 256
EARTH_MPP_Z0 = 156543.03392804097       # metres per pixel at zoom 0 on the equator
MAX_ZOOM = 19
MAX_PICTURE_PX = 4096
USER_AGENT = "CAMS/1.3 (Camera AI Management System; offline campus map)"

SOURCES = {
    "imagery": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "jpg"),
    "labels": ("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", "png"),
}
ATTRIBUTION = "Satellite imagery: Esri, Maxar, Earthstar Geographics and the GIS user community"


class GeoError(Exception):
    pass


# ---------------------------------------------------------------- projection
def lnglat_to_px(lng: float, lat: float, z: float) -> tuple[float, float]:
    """Global Web Mercator pixel of a point at zoom z."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = TILE * 2 ** z
    x = (lng + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def px_to_lnglat(x: float, y: float, z: float) -> tuple[float, float]:
    n = TILE * 2 ** z
    lng = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lng, lat


def metres_per_px(lat: float, z: float) -> float:
    return EARTH_MPP_Z0 * math.cos(math.radians(lat)) / 2 ** z


class Georef:
    """Converts between map metres and latitude / longitude."""

    def __init__(self, lat: float, lng: float, width_m: float, height_m: float):
        self.lat, self.lng = float(lat), float(lng)
        self.w, self.h = float(width_m), float(height_m)
        self.z = 20  # any zoom works; 20 keeps numbers well conditioned
        self.cx, self.cy = lnglat_to_px(self.lng, self.lat, self.z)
        self.mpp = metres_per_px(self.lat, self.z)

    def to_latlng(self, x: float, y: float) -> tuple[float, float]:
        px = self.cx + (x - self.w / 2) / self.mpp
        py = self.cy + (y - self.h / 2) / self.mpp
        lng, lat = px_to_lnglat(px, py, self.z)
        return round(lat, 7), round(lng, 7)

    def to_map(self, lat: float, lng: float) -> tuple[float, float]:
        px, py = lnglat_to_px(lng, lat, self.z)
        return (px - self.cx) * self.mpp + self.w / 2, (py - self.cy) * self.mpp + self.h / 2


def georef_from_settings(s: dict) -> Georef | None:
    try:
        lat, lng = float(s.get("geo_lat") or ""), float(s.get("geo_lng") or "")
    except ValueError:
        return None
    if not (-85 < lat < 85 and -180 <= lng <= 180):
        return None
    return Georef(lat, lng, float(s.get("map_width_m", 200)), float(s.get("map_height_m", 150)))


def parse_location(text: str) -> tuple[float, float] | None:
    """Read a position typed by a person: "-6.7701, 39.2405", a Google Maps or
    OpenStreetMap link, or degrees with N/S/E/W ("6.77 S 39.24 E")."""
    t = urllib.parse.unquote(text or "").strip()
    if not t:
        return None
    pats = [
        r"@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)",              # google .../@lat,lng,17z
        r"[?&](?:q|query|ll|center|destination)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)",
        r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)",              # google place data
        r"#map=\d+/(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)",         # openstreetmap
        r"mlat=(-?\d+(?:\.\d+)?)&mlon=(-?\d+(?:\.\d+)?)",
    ]
    for p in pats:
        m = re.search(p, t)
        if m:
            return _check(float(m.group(1)), float(m.group(2)))
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*°?\s*([NSns])[\s,]+(\d+(?:\.\d+)?)\s*°?\s*([EWew])\s*", t)
    if m:
        lat = float(m.group(1)) * (-1 if m.group(2).upper() == "S" else 1)
        lng = float(m.group(3)) * (-1 if m.group(4).upper() == "W" else 1)
        return _check(lat, lng)
    m = re.fullmatch(r"\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)\s*\)?\s*", t)
    if m:
        return _check(float(m.group(1)), float(m.group(2)))
    return None


def _check(lat: float, lng: float) -> tuple[float, float] | None:
    return (lat, lng) if -85 < lat < 85 and -180 <= lng <= 180 else None


# ---------------------------------------------------------------- tiles
class TileCache:
    """Downloads map tiles once and keeps them on disk for offline use."""

    def __init__(self, folder: Path, fetch=None):
        self.folder = Path(folder)
        self._fetch = fetch or self._download
        self._lock = threading.Lock()

    def path(self, source: str, z: int, x: int, y: int) -> Path:
        ext = SOURCES[source][1]
        return self.folder / source / str(z) / str(x) / f"{y}.{ext}"

    def get(self, source: str, z: int, x: int, y: int, *, online: bool = True) -> bytes | None:
        if source not in SOURCES:
            raise GeoError("Unknown map source.")
        if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
            return None
        p = self.path(source, z, x, y)
        if p.is_file():
            return p.read_bytes()
        if not online:
            return None
        url = SOURCES[source][0].format(z=z, x=x, y=y)
        data = self._fetch(url)
        if data:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(p)
        return data

    @staticmethod
    def _download(url: str) -> bytes | None:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 200:
                    return None
                return r.read()
        except Exception:
            return None

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.folder.rglob("*") if f.is_file()) if self.folder.exists() else 0


def choose_zoom(lat: float, width_m: float, height_m: float, max_px: int = MAX_PICTURE_PX) -> int:
    for z in range(MAX_ZOOM, 0, -1):
        mpp = metres_per_px(lat, z)
        if width_m / mpp <= max_px and height_m / mpp <= max_px:
            return z
    return 1


def satellite_picture(tiles: TileCache, lat: float, lng: float, width_m: float, height_m: float,
                      progress=None) -> tuple[np.ndarray, dict]:
    """Stitch the satellite picture of a width_m x height_m area centred on (lat, lng)."""
    if width_m < 10 or height_m < 10:
        raise GeoError("The area must be at least 10 m across.")
    if width_m > 20000 or height_m > 20000:
        raise GeoError("The area is too big (max 20 km).")
    z = choose_zoom(lat, width_m, height_m)
    mpp = metres_per_px(lat, z)
    cx, cy = lnglat_to_px(lng, lat, z)
    x0, y0 = cx - width_m / mpp / 2, cy - height_m / mpp / 2
    x1, y1 = cx + width_m / mpp / 2, cy + height_m / mpp / 2
    tx0, ty0, tx1, ty1 = int(x0 // TILE), int(y0 // TILE), int(x1 // TILE), int(y1 // TILE)
    jobs = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    canvas = np.full(((ty1 - ty0 + 1) * TILE, (tx1 - tx0 + 1) * TILE, 3), 200, np.uint8)
    done = [0]
    missing = [0]

    def one(job):
        tx, ty = job
        data = tiles.get("imagery", z, tx % 2 ** z, ty)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
        if img is None:
            missing[0] += 1
        else:
            if img.shape[:2] != (TILE, TILE):
                img = cv2.resize(img, (TILE, TILE))
            oy, ox = (ty - ty0) * TILE, (tx - tx0) * TILE
            canvas[oy:oy + TILE, ox:ox + TILE] = img
        done[0] += 1
        if progress:
            progress(done[0], len(jobs))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, jobs))
    if missing[0] == len(jobs):
        raise GeoError("Could not download the satellite picture. Check that this PC is connected to the internet, then try again.")
    ox, oy = x0 - tx0 * TILE, y0 - ty0 * TILE
    crop = canvas[int(round(oy)):int(round(oy + height_m / mpp)), int(round(ox)):int(round(ox + width_m / mpp))]
    info = {"zoom": z, "metres_per_pixel": round(mpp, 3), "tiles": len(jobs), "missing": missing[0],
            "width_px": int(crop.shape[1]), "height_px": int(crop.shape[0])}
    return crop.copy(), info


# ---------------------------------------------------------------- place search
def search_places(q: str, limit: int = 6) -> list[dict]:
    """Find a place by name (OpenStreetMap Nominatim). Needs internet."""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": limit})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read().decode("utf-8"))
    except Exception:
        raise GeoError("Place search needs the internet. You can also paste a Google Maps link or type the coordinates.")
    return [{"name": r.get("display_name", ""), "lat": float(r["lat"]), "lng": float(r["lon"])} for r in rows]
