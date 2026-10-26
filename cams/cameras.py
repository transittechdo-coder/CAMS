"""Camera connections.

CAMS accepts any camera OpenCV can read:

* USB / built-in webcams  -> source "0", "1", ...          (kind "usb")
* IP / Ethernet / PoE / NVR channels over RTSP
                          -> "rtsp://user:pass@192.168.1.20:554/..."  (kind "rtsp")
* HTTP MJPEG / snapshot streams (phones running IP-camera apps, older cams)
                          -> "http://192.168.1.30:8080/video"         (kind "http")
* Video files for demos and testing -> "C:\\videos\\gate.mp4"          (kind "file")

Each camera gets a background thread that keeps only the newest frame, so a
slow analysis step never builds up a backlog, and reconnects automatically
when the network drops.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from ipaddress import IPv4Network
from typing import Callable

import cv2
import numpy as np

# Prefer TCP for RTSP: far fewer grey/smeared frames on busy school networks.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")

RECONNECT_SECONDS = 5
OFFLINE_ALERT_SECONDS = 60

# RTSP address patterns for common brands, shown as hints in the "Add camera"
# dialog. {user} {password} {ip} {channel} are filled in by the UI.
RTSP_TEMPLATES = {
    "Hikvision / HiLook": "rtsp://{user}:{password}@{ip}:554/Streaming/Channels/{channel}01",
    "Dahua / Imou": "rtsp://{user}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0",
    "Uniview": "rtsp://{user}:{password}@{ip}:554/unicast/c{channel}/s0/live",
    "TP-Link Tapo / VIGI": "rtsp://{user}:{password}@{ip}:554/stream1",
    "Reolink": "rtsp://{user}:{password}@{ip}:554/h264Preview_0{channel}_main",
    "Axis": "rtsp://{user}:{password}@{ip}/axis-media/media.amp",
    "EZVIZ": "rtsp://admin:{password}@{ip}:554/H.264",
    "Generic ONVIF": "rtsp://{user}:{password}@{ip}:554/",
    "Android IP Webcam app (HTTP)": "http://{ip}:8080/video",
}


def detect_kind(source: str) -> str:
    s = source.strip().lower()
    if s.isdigit():
        return "usb"
    if s.startswith(("rtsp://", "rtsps://")):
        return "rtsp"
    if s.startswith(("http://", "https://")):
        return "http"
    return "file"


def open_capture(source: str, kind: str) -> cv2.VideoCapture:
    if kind == "usb":
        index = int(source)
        if sys.platform.startswith("win"):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
        else:
            cap = cv2.VideoCapture(index)
    elif kind in ("rtsp", "http"):
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(source)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except cv2.error:
        pass
    return cap


def mask_source(source: str) -> str:
    """Hide the password in an rtsp://user:pass@host address for display."""
    if "://" in source and "@" in source:
        scheme, rest = source.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:****@{host}"
    return source


@dataclass
class CameraState:
    id: int
    name: str
    source: str
    kind: str
    status: str = "starting"          # starting | online | offline | stopped
    error: str = ""
    fps: float = 0.0
    width: int = 0
    height: int = 0
    last_frame_at: float = 0.0
    offline_since: float | None = None
    offline_alerted: bool = False
    # Latest analysis result, drawn on the live view.
    overlays: list[dict] = field(default_factory=list)
    people: list[list[int]] = field(default_factory=list)   # person-detector boxes
    overlays_at: float = 0.0


class CameraWorker:
    def __init__(self, cam: dict, on_frame: Callable[["CameraWorker", np.ndarray], None] | None = None):
        self.state = CameraState(
            id=cam["id"], name=cam["name"], source=cam["source"], kind=cam.get("kind") or detect_kind(cam["source"])
        )
        self.restricted = bool(cam.get("restricted"))
        self.on_frame = on_frame
        self._frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"cam-{cam['id']}", daemon=True)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 3) -> None:
        self._stop.set()
        self._thread.join(timeout)
        self.state.status = "stopped"

    @property
    def id(self) -> int:
        return self.state.id

    def latest(self) -> np.ndarray | None:
        with self._frame_lock:
            return None if self._frame is None else self._frame.copy()

    # ------------------------------------------------------------ loop
    def _run(self) -> None:
        st = self.state
        while not self._stop.is_set():
            cap = open_capture(st.source, st.kind)
            if not cap.isOpened():
                self._mark_offline("Cannot connect. Check the address, username/password and that the camera is powered.")
                cap.release()
                self._stop.wait(RECONNECT_SECONDS)
                continue
            st.status, st.error = "online", ""
            st.offline_since, st.offline_alerted = None, False
            native_fps = cap.get(cv2.CAP_PROP_FPS) or 0
            frame_delay = 1.0 / native_fps if st.kind == "file" and native_fps > 0 else 0.0
            frames, t0 = 0, time.time()
            failures = 0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    if st.kind == "file":           # loop demo videos
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, frame = cap.read()
                    if not ok or frame is None:
                        failures += 1
                        if failures > 25:
                            break
                        time.sleep(0.05)
                        continue
                failures = 0
                now = time.time()
                with self._frame_lock:
                    self._frame = frame
                st.last_frame_at = now
                st.height, st.width = frame.shape[:2]
                frames += 1
                if now - t0 >= 2:
                    st.fps = round(frames / (now - t0), 1)
                    frames, t0 = 0, now
                if self.on_frame:
                    try:
                        self.on_frame(self, frame)
                    except Exception as exc:  # never let analysis kill capture
                        st.error = f"analysis: {exc}"
                if frame_delay:
                    time.sleep(frame_delay)
            cap.release()
            if not self._stop.is_set():
                self._mark_offline("Stream stopped. Reconnecting...")
                self._stop.wait(RECONNECT_SECONDS)

    def _mark_offline(self, msg: str) -> None:
        st = self.state
        st.status, st.error, st.fps = "offline", msg, 0.0
        if st.offline_since is None:
            st.offline_since = time.time()


def test_source(source: str, kind: str | None = None, timeout: float = 8.0) -> dict:
    """Try to grab one frame. Used by the 'Test connection' button."""
    kind = kind or detect_kind(source)
    result: dict = {"ok": False, "kind": kind}

    def attempt():
        cap = open_capture(source, kind)
        try:
            if not cap.isOpened():
                result["error"] = "Could not open the stream."
                return
            ok, frame = cap.read()
            if not ok or frame is None:
                result["error"] = "Connected, but no picture was received."
                return
            result.update(ok=True, width=int(frame.shape[1]), height=int(frame.shape[0]))
            okj, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if okj:
                result["jpeg"] = buf.tobytes()
        finally:
            cap.release()

    t = threading.Thread(target=attempt, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        result["error"] = "Timed out. The camera did not answer."
    return result


# ---------------------------------------------------------------- discovery
def local_subnets() -> list[IPv4Network]:
    """Best guess at this PC's LAN /24 networks (no internet needed)."""
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # no packet is sent for UDP connect
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    nets = []
    for ip in ips:
        if ip.startswith("127."):
            continue
        nets.append(IPv4Network(f"{ip}/24", strict=False))
    return sorted(set(nets), key=str)


def _probe(ip: str, ports=(554, 8554, 80, 8080, 8000), timeout=0.4) -> dict | None:
    open_ports = []
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                open_ports.append(port)
        except OSError:
            continue
    if 554 in open_ports or 8554 in open_ports:
        return {"ip": ip, "ports": open_ports, "likely_camera": True}
    if open_ports and (8080 in open_ports or 8000 in open_ports):
        return {"ip": ip, "ports": open_ports, "likely_camera": False}
    return None


def scan_network(subnet: str | None = None, max_workers: int = 128) -> list[dict]:
    """Find devices on the LAN with a camera streaming port open (RTSP 554)."""
    nets = [IPv4Network(subnet, strict=False)] if subnet else local_subnets()
    hosts = [str(h) for n in nets if n.num_addresses <= 1024 for h in n.hosts()]
    found = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for r in pool.map(_probe, hosts):
            if r:
                found.append(r)
    return sorted(found, key=lambda d: tuple(int(p) for p in d["ip"].split(".")))
