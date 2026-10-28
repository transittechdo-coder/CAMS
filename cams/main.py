"""Start CAMS: the local server plus a desktop window.

    python -m cams              # normal start (opens the CAMS window)
    python -m cams --no-window  # no window (developers): open http://127.0.0.1:8765 yourself
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


# ---------------------------------------------------------------- the window
# CAMS shows its screens in its own app window. Behind the window there is a
# small private web server that only this computer can reach (127.0.0.1);
# that needs no administrator rights and no internet.

def _find_edge() -> str | None:
    """Microsoft Edge (on every Windows 10/11 PC) or Chrome, for the app window fallback."""
    import shutil

    candidates = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def _window_webview(url: str, ready=None) -> bool:
    """Native window via pywebview + Edge WebView2 (Windows 10/11)."""
    try:
        import webview  # type: ignore
    except Exception as exc:
        logging.getLogger("cams").info("pywebview not available: %s", exc)
        return False
    try:
        win = webview.create_window("CAMS - Camera AI Management System", url, width=1360, height=860,
                                    min_size=(1000, 640), background_color="#EEF2F0")
        kwargs = {"private_mode": False, "storage_path": str(get_paths().data / "webview")}
        if sys.platform.startswith("win"):
            kwargs["gui"] = "edgechromium"   # never fall back to old Internet Explorer
        func = (lambda: ready(win.destroy)) if ready else None
        webview.start(func, **kwargs)
        return True
    except Exception as exc:  # e.g. WebView2 runtime missing
        logging.getLogger("cams").warning("Native window unavailable (%s)", exc)
        return False


def _window_edge_app(url: str, ready=None) -> bool:
    """Edge/Chrome 'app mode': its own window with no address bar or tabs."""
    import subprocess

    exe = _find_edge()
    if not exe:
        return False
    profile = get_paths().data / "window"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
           "--window-size=1360,860", "--disable-features=Translate"]
    if os.environ.get("CAMS_HEADLESS_CHECK") == "1":
        cmd.insert(1, "--headless=new")
    if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")   # Chromium refuses to run as root otherwise (test machines)
    try:
        proc = subprocess.Popen(cmd)
    except OSError as exc:
        logging.getLogger("cams").warning("Could not open the app window: %s", exc)
        return False
    if ready:
        ready(proc.terminate)
    proc.wait()
    return True


def _clear_window_cache() -> None:
    """After an update, drop the window's saved copies of the old screens.

    Only the browser caches are removed (not sign-ins or settings), and only
    once per new version.
    """
    import shutil

    from . import __version__

    data = get_paths().data
    marker = data / "window-version.txt"
    try:
        if marker.is_file() and marker.read_text().strip() == __version__:
            return
        for root in (data / "webview", data / "window"):
            if not root.is_dir():
                continue
            for name in ("Cache", "Code Cache", "GPUCache", "Service Worker", "DawnCache", "DawnGraphiteCache"):
                for d in root.rglob(name):
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
        marker.write_text(__version__)
    except OSError as exc:
        logging.getLogger("cams").warning("Could not clear the window cache: %s", exc)


def _open_window(url: str, ready=None) -> str:
    """Open the CAMS window and return when the user closes it. Returns the mode used."""
    _splash(close=True)
    _clear_window_cache()
    if _window_webview(url, ready):
        return "webview"
    if _window_edge_app(url, ready):
        return "app-window"
    webbrowser.open(url)
    if ready:
        done = threading.Event()
        ready(done.set)
        done.wait(65)
    return "browser"


# ---------------------------------------------------------------- feedback
def _splash(text: str | None = None, close: bool = False) -> None:
    """Loading picture shown by CAMS.exe the moment it is opened (PyInstaller splash)."""
    try:
        import pyi_splash  # type: ignore  # only exists inside the built CAMS.exe
    except Exception:
        return
    try:
        if close:
            pyi_splash.close()
        elif text and pyi_splash.is_alive():
            pyi_splash.update_text(text)
    except Exception:
        pass


def _message(title: str, text: str) -> None:
    """Show a plain Windows message box (nothing is ever silent)."""
    _splash(close=True)
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 | 0x40000)  # error icon, top-most
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)


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
        _splash(close=True)
        raise
    except Exception as exc:
        logging.getLogger("cams").exception("CAMS stopped because of an error")
        logs = get_paths().logs / "cams.log"
        _message("CAMS could not start",
                 f"CAMS could not start:\n\n{exc}\n\nDetails are saved in:\n{logs}\n\n"
                 "Try opening CAMS again. If it keeps happening, send this file to TransitTech.")
        return 1
    finally:
        _splash(close=True)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cams", description=APP_FULL_NAME)
    ap.add_argument("--no-window", action="store_true", help="run the server only")
    ap.add_argument("--lan", action="store_true", help="listen on all network interfaces")
    ap.add_argument("--port", type=int, default=SERVER_PORT)
    ap.add_argument("--check-window", action="store_true",
                    help="open the window, confirm the screens load, close it and report (used by the build checks)")
    ap.add_argument("--version", action="version", version=f"CAMS {__version__}")
    args = ap.parse_args(argv)

    host = "0.0.0.0" if args.lan or os.environ.get("CAMS_LAN") == "1" else SERVER_HOST
    paths = get_paths()
    paths.ensure()
    run_file = paths.data / "running.json"

    # CAMS already open? Show another window for it instead of starting twice.
    try:
        prev = json.loads(run_file.read_text())["port"]
    except Exception:
        prev = None
    for port in [p for p in (prev, args.port) if p]:
        if _already_running(port) and not args.check_window:
            _splash(close=True)
            if not args.no_window:
                _open_window(f"http://127.0.0.1:{port}/")
            return 0

    port = args.port
    if not _port_free(host, port):
        # Another program uses our usual port: quietly pick a free one.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_:
            s_.bind((host, 0))
            port = s_.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"

    _setup_logging(paths)
    _splash("Loading face recognition...")
    log = logging.getLogger("cams")
    log.info("Starting CAMS %s, data in %s", __version__, paths.data)

    import uvicorn

    from .api import create_app
    from .system import CamsSystem

    system = CamsSystem(paths)
    _splash("Connecting cameras...")
    system.start()
    app = create_app(system)
    # log_config=None: use our own logging (uvicorn's default needs a console)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False, log_config=None)
    server = uvicorn.Server(config)

    if args.no_window:
        _splash(close=True)
        print(f"CAMS is running at {url}  (Ctrl+C to stop)")
        try:
            server.run()
        finally:
            system.stop()
        return 0

    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    _splash("Opening CAMS...")
    if not _wait_ready(port):
        log.error("Server did not start")
        system.stop()
        raise RuntimeError("The CAMS engine did not start within 30 seconds.")
    try:
        run_file.write_text(json.dumps({"port": port, "pid": os.getpid()}))
    except OSError:
        pass

    ready = None
    result = {"ok": False}
    if args.check_window:
        def ready(close):
            def watch():
                end = time.time() + 60
                while time.time() < end and system.stats.get("ui_loads", 0) < 1:
                    time.sleep(0.3)
                result["ok"] = system.stats.get("ui_loads", 0) >= 1
                time.sleep(1)
                close()
            threading.Thread(target=watch, daemon=True).start()

    try:
        mode = _open_window(url, ready)
        log.info("CAMS window mode: %s", mode)
        if mode == "browser" and not args.check_window:
            # Last resort only: keep running while the browser tab is used.
            while t.is_alive():
                t.join(1)
    except KeyboardInterrupt:
        mode = "stopped"
    finally:
        server.should_exit = True
        system.stop()
        t.join(5)
        try:
            run_file.unlink()
        except OSError:
            pass
    if args.check_window:
        out = {"ok": result["ok"], "mode": mode, "version": __version__}
        (paths.data / "window_check.json").write_text(json.dumps(out))
        print(json.dumps(out))
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
