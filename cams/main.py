"""Start CAMS: the local server plus a desktop window.

    python -m cams              # normal start (opens the CAMS window)
    python -m cams --no-window  # server only, open http://127.0.0.1:8765 yourself
    python -m cams --lan        # also allow other PCs on the network to sign in
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from . import APP_FULL_NAME, __version__
from .config import SERVER_HOST, SERVER_PORT, get_paths


def _setup_logging(paths) -> None:
    paths.logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(paths.logs / "cams.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr and getattr(sys.stderr, "name", "") != os.devnull:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.5) as r:
            return json.loads(r.read()).get("app") == "CAMS"
    except Exception:
        return False


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _wait_ready(port: int, timeout: float = 30) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _already_running(port):
            return True
        time.sleep(0.3)
    return False


def _open_window(url: str) -> bool:
    """Native window via pywebview (Edge WebView2 on Windows). False if unavailable."""
    try:
        import webview  # type: ignore
    except Exception:
        return False
    try:
        webview.create_window(f"CAMS - {APP_FULL_NAME}", url, width=1360, height=860, min_size=(1000, 640))
        # private_mode=False keeps sign-in and preferences between runs
        webview.start(private_mode=False, storage_path=str(get_paths().data / "webview"))
        return True
    except Exception as exc:  # e.g. WebView2 runtime missing on an old Windows
        logging.getLogger("cams").warning("Native window unavailable (%s); using the browser", exc)
        return False


def _ensure_streams() -> None:
    """A windowed .exe has no console: sys.stdout/stderr are None and some
    libraries crash when they try to write or check isatty(). Give them a sink."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _ensure_streams()
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception:
        logging.getLogger("cams").exception("CAMS stopped because of an error")
        raise


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cams", description=APP_FULL_NAME)
    ap.add_argument("--no-window", action="store_true", help="run the server only")
    ap.add_argument("--lan", action="store_true", help="listen on all network interfaces")
    ap.add_argument("--port", type=int, default=SERVER_PORT)
    ap.add_argument("--version", action="version", version=f"CAMS {__version__}")
    args = ap.parse_args(argv)

    host = "0.0.0.0" if args.lan or os.environ.get("CAMS_LAN") == "1" else SERVER_HOST
    url = f"http://127.0.0.1:{args.port}/"

    if _already_running(args.port):
        # CAMS is already open (maybe minimised): just show it again.
        if args.no_window or not _open_window(url):
            webbrowser.open(url)
        return 0
    if not _port_free(host, args.port):
        print(f"Port {args.port} is used by another program. Start with --port 8770", file=sys.stderr)
        return 2

    paths = get_paths()
    paths.ensure()
    _setup_logging(paths)
    log = logging.getLogger("cams")
    log.info("Starting CAMS %s, data in %s", __version__, paths.data)

    import uvicorn

    from .api import create_app
    from .system import CamsSystem

    system = CamsSystem(paths)
    system.start()
    app = create_app(system)
    # log_config=None: use our own logging (uvicorn's default needs a console)
    config = uvicorn.Config(app, host=host, port=args.port, log_level="warning", access_log=False, log_config=None)
    server = uvicorn.Server(config)

    if args.no_window:
        print(f"CAMS is running at {url}  (Ctrl+C to stop)")
        try:
            server.run()
        finally:
            system.stop()
        return 0

    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    if not _wait_ready(args.port):
        log.error("Server did not start")
        return 1
    try:
        if not _open_window(url):
            # No native window available: use the default browser and keep running.
            webbrowser.open(url)
            print(f"CAMS is running at {url}  (close this window to stop)")
            while t.is_alive():
                t.join(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        system.stop()
        t.join(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
