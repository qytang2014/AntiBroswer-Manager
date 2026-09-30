"""Native/frozen entry point for AntiBrowser-Manager.

This is the PyInstaller target. Unlike run.py (the dev-from-source launcher,
which shells out to `uvicorn backend.main:app`), a frozen bundle cannot resolve
the "backend.main:app" import string, so uvicorn is run in-process here.

Serves on 127.0.0.1:52341. The UI is shown in one of two shells, chosen by the
CLOAKBROWSER_MANAGER_UI env var:
  - "webview" — a dedicated native app window (WKWebView on macOS, WebView2 on
    Windows) via pywebview. No browser chrome, its own Dock/taskbar entry.
  - "browser" — the user's default browser at the server URL (the original
    behavior).
  - "auto"    — (default) webview if pywebview is importable, else browser.

There is no visible terminal in the packaged app — logs go to a rotating file
in the data dir (see backend/main.py logging setup).
"""

from __future__ import annotations

import sys
if "-c" in sys.argv:
    idx = sys.argv.index("-c")
    if idx + 1 < len(sys.argv):
        code = sys.argv[idx + 1]
        if "multiprocessing" in code:
            exec(code)
            sys.exit(0)


import json
import os
import socket
import threading
import time
import urllib.request

DEFAULT_PORT = 52341
HOST = "127.0.0.1"
WINDOW_TITLE = "AntiBrowser-Manager"


def _is_port_bindable(port: int, host: str = HOST, retries: int = 1, retry_delay: float = 0.2) -> bool:
    for i in range(retries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return True
            except OSError:
                if i < retries - 1:
                    time.sleep(retry_delay)
    return False


def _get_dynamic_free_port(host: str = HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _probe_manager_health(port: int, host: str = HOST) -> dict | None:
    try:
        url = f"http://{host}:{port}/api/health"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AntiBrowser-Manager-Probe"},
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and data.get("app") == "antibrowser-manager":
                    return data
    except Exception:
        pass
    return None


def _shutdown_remote_instance(port: int, host: str = HOST) -> bool:
    try:
        url = f"http://{host}:{port}/api/shutdown"
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={
                "User-Agent": "AntiBrowser-Manager-Updater",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def _wait_for_port_release(port: int, host: str = HOST, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_port_bindable(port, host):
            return True
        time.sleep(0.2)
    return False


def _wait_until_ready(server_url: str, timeout: float = 180.0) -> bool:
    """Poll /api/health until the server answers or the timeout elapses.

    First launch may download the stealth Chromium binary (140MB), which
    can take 30-60s depending on network speed.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{server_url}/api/health", timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _save_server_info(port: int, host: str, url: str) -> None:
    try:
        from backend.runtime import resolve_runtime

        path = resolve_runtime().data_dir / "server_info.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"port": port, "host": host, "url": url, "pid": os.getpid()},
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _resolve_server_port() -> tuple[int, bool]:
    """Determine the server port to listen on.

    Returns:
        (port, should_run)
        - If should_run is False, an existing instance of the same version is running
          and was focused; caller should exit cleanly with 0.
        - If should_run is True, port is allocated and ready to bind.
    """
    import sys
    import os

    # If launched with browser/child-process arguments (e.g. from Playwright inheriting sys.executable),
    # silently exit to prevent showing the "Already running" notification for spurious child processes.
    if any(arg in ("-no-remote", "--type=renderer", "--type=gpu-process", "--headless") for arg in sys.argv):
        return DEFAULT_PORT, False
    if "PW_LANG_NAME" in os.environ or "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        return DEFAULT_PORT, False

    env_port = os.environ.get("PORT")
    preferred_port = int(env_port) if env_port and env_port.isdigit() else DEFAULT_PORT

    if _is_port_bindable(preferred_port, HOST):
        return preferred_port, True

    # preferred_port is occupied; probe for existing AntiBrowser-Manager
    probe_data = _probe_manager_health(preferred_port, HOST)
    if probe_data is not None:
        from backend.diagnostics import app_version

        running_version = str(probe_data.get("version") or "")
        my_version = str(app_version() or "")

        if running_version == my_version and running_version != "unknown":
            # Same version: activate window and exit without opening browser
            _focus_existing_window()
            import sys

            if sys.platform == "darwin":
                try:
                    import subprocess

                    subprocess.run(
                        [
                            "osascript",
                            "-e",
                            'display notification "AntiBrowser-Manager 已在运行中，请查看 Dock 或已打开的窗口。" with title "AntiBrowser-Manager"',
                        ],
                        capture_output=True,
                        timeout=2,
                    )
                except Exception:
                    pass
            print(
                f"[info] AntiBrowser-Manager (v{running_version}) is already running on port {preferred_port}."
            )
            return preferred_port, False

        # Older or different version: request shutdown to let new version take over
        print(
            f"[upgrade] Existing instance (v{running_version}) detected on port {preferred_port}. Shutting down to upgrade to v{my_version}..."
        )
        _shutdown_remote_instance(preferred_port, HOST)
        if _wait_for_port_release(preferred_port, HOST, timeout=5.0):
            print(f"[upgrade] Port {preferred_port} released. Starting updated version...")
            return preferred_port, True

        # If port not released in 5s, allocate OS dynamic port
        print(
            f"[upgrade] Port {preferred_port} not freed in time. Allocating dynamic port..."
        )
        return _get_dynamic_free_port(HOST), True

    # Occupied by third-party application: allocate OS dynamic port immediately
    dynamic_port = _get_dynamic_free_port(HOST)
    print(
        f"[info] Port {preferred_port} is in use by another application. Dynamically allocated port {dynamic_port}."
    )
    return dynamic_port, True


def _window_state_path():
    # Its own file (not settings.json): save_settings() rewrites the whole
    # settings dict, so persisting geometry there could clobber a license key
    # the backend saved concurrently. Geometry writes stay isolated here.
    from backend.runtime import resolve_runtime

    return resolve_runtime().data_dir / "window.json"


def _load_window_geometry() -> dict:
    import json

    try:
        data = json.loads(_window_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in ("x", "y", "width", "height"):
        value = data.get(key)
        if isinstance(value, int) and value >= 0:
            out[key] = value
    return out


def _save_window_geometry(state: dict) -> None:
    import json
    import tempfile

    path = _window_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(tmp, path)
    except OSError:
        pass  # geometry persistence is a nicety, never fatal


def _ui_mode() -> str:
    mode = os.environ.get("CLOAKBROWSER_MANAGER_UI", "auto").strip().lower()
    if mode not in {"auto", "webview", "browser"}:
        mode = "auto"
    if mode == "auto":
        try:
            import webview  # noqa: F401
        except ImportError:
            return "browser"
        return "webview"
    return mode


def _set_app_icon() -> None:
    """Show our mark in the Dock/taskbar for the from-source dev run.

    The frozen build already carries the icon (manager.spec BUNDLE(icon=…) on
    macOS; the PyInstaller/Inno .ico on Windows), so this is dev-only:
    `python app_entry.py` from source otherwise shows the interpreter's generic
    icon (Python.app rocket on macOS, python.exe on Windows). No-op on failure /
    unsupported platform / frozen.
    """
    import sys
    from pathlib import Path

    if getattr(sys, "frozen", False):
        return
    packaging = Path(__file__).resolve().parent / "packaging"

    if sys.platform == "darwin":
        # The rounded squircle (icon.icns), NOT icon.png (the square master).
        icon = packaging / "icon.icns"
        if not icon.exists():
            icon = packaging / "icon.png"
        if not icon.exists():
            return
        try:
            from AppKit import NSApplication, NSImage

            image = NSImage.alloc().initWithContentsOfFile_(str(icon))
            if image is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(image)
        except Exception:
            pass

    elif sys.platform == "win32":
        icon = packaging / "icon.ico"
        if not icon.exists():
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            image_icon, lr_loadfromfile, lr_defaultsize = 1, 0x10, 0x40
            wm_seticon, icon_small, icon_big = 0x0080, 0, 1
            hicon = user32.LoadImageW(
                None, str(icon), image_icon, 0, 0,
                lr_loadfromfile | lr_defaultsize,
            )
            if hicon:
                # FindWindow by our exact title — the pywebview window is the
                # only one using it. Set both title-bar and taskbar icons.
                hwnd = user32.FindWindowW(None, WINDOW_TITLE)
                if hwnd:
                    user32.SendMessageW(hwnd, wm_seticon, icon_small, hicon)
                    user32.SendMessageW(hwnd, wm_seticon, icon_big, hicon)
        except Exception:
            pass


def _focus_existing_window() -> bool:
    """Raise an already-running Manager's window — single-instance.

    On Windows, find our window by title and bring it to the foreground.
    On macOS, activate the native AntiBrowser-Manager application.
    Returns True if a window was focused. No-op / False on other platforms.
    """
    import sys

    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, WINDOW_TITLE)
            if not hwnd:
                return False
            sw_restore = 9
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, sw_restore)
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False
    elif sys.platform == "darwin":
        try:
            import subprocess

            script = (
                'try\n'
                'tell application id "dev.cloakbrowser.manager" to activate\n'
                'on error\n'
                'tell application "AntiBrowser-Manager" to activate\n'
                'end try'
            )
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=2,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass
        return False
    return False


def _run_webview(server, server_url: str) -> int:
    """Run the server in a background thread and the native window on main.

    macOS/Cocoa requires the webview event loop to own the main thread, so the
    uvicorn server is threaded here. uvicorn's install_signal_handlers()
    early-returns off the main thread, so a threaded server.run() is safe.
    """
    import sys

    import webview

    # Windows taskbar groups/icons by AppUserModelID; set an explicit one before
    # the window exists so the dev-run taskbar icon can be ours (frozen build is
    # unaffected — it has a real .exe identity). No-op elsewhere / on failure.
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "dev.cloakbrowser.manager"
            )
        except Exception:
            pass

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not _wait_until_ready(server_url):
        # Server never came up — log the failure. Never open browser automatically.
        print(f"[error] Server failed to start at {server_url}", file=sys.stderr, flush=True)
        server.should_exit = True
        server_thread.join(timeout=10)
        return 1

    geometry = _load_window_geometry()
    window_kwargs = {
        "width": geometry.get("width", 1400),
        "height": geometry.get("height", 900),
        "min_size": (1000, 700),
    }
    if "x" in geometry and "y" in geometry:
        window_kwargs["x"] = geometry["x"]
        window_kwargs["y"] = geometry["y"]
    window = webview.create_window(WINDOW_TITLE, server_url, **window_kwargs)

    # Track live geometry so we can restore the window next launch. Saved once
    # on close (below) rather than on every resize/move tick.
    state = dict(geometry)

    def _on_resized(width, height):
        state["width"], state["height"] = int(width), int(height)

    def _on_moved(x, y):
        state["x"], state["y"] = int(x), int(y)

    window.events.resized += _on_resized
    window.events.moved += _on_moved
    # Set the Dock/taskbar icon once the window exists, on the main thread.
    # Dev-only nicety; the frozen build already shows the icon.
    window.events.shown += _set_app_icon

    webview.start()  # blocks on the main thread until the window is closed

    # Window closed (incl. Cmd+Q via the default macOS menu) → persist geometry,
    # then shut the server down cleanly (the lifespan shutdown closes every
    # profile via cleanup_all()).
    _save_window_geometry(state)
    server.should_exit = True
    server_thread.join(timeout=15)
    return 0


def _harden_std_streams() -> None:
    """Make stdout/stderr non-fatal on non-ASCII output.

    A frozen GUI app on Windows has no console, so sys.stdout/stderr carry the
    legacy console codepage (cp1252) with errors="strict". A dependency writing
    a glyph that codepage lacks (e.g. the cloakbrowser welcome banner's → and —,
    printed on the first Pro-binary download) then raises UnicodeEncodeError.
    Because that write sits on the binary-download path, the exception aborts the
    whole profile launch. Switch both streams to errors="replace" so an
    unencodable glyph degrades to '?' instead of crashing the process.
    """
    import sys

    # Snapshot the real encoding BEFORE reconfiguring, so the startup
    # fingerprint records the cp1252/strict that actually crashes, not "replace".
    try:
        from backend import diagnostics

        diagnostics.capture_stream_state()
    except Exception:
        pass

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def main() -> int:
    _harden_std_streams()
    os.environ.setdefault("CLOAKBROWSER_MANAGER_RUNTIME", "native")
    try:
        from backend.runtime import resolve_runtime
        resolve_runtime()
    except Exception:
        pass

    port, should_run = _resolve_server_port()
    if not should_run:
        return 0

    server_url = f"http://{HOST}:{port}"
    _save_server_info(port, HOST, server_url)

    import uvicorn
    from backend.main import app

    app.state.server_port = port
    app.state.server_host = HOST
    app.state.server_url = server_url

    # log_config=None lets uvicorn's own loggers propagate to the root handlers
    # configured in backend/main.py (console + rotating file), instead of
    # uvicorn installing its own console-only handlers.
    #
    # Build the Server explicitly (instead of uvicorn.run) and stash it on
    # app.state so the /api/shutdown endpoint can flip should_exit for a clean
    # cross-platform quit from the UI.
    config = uvicorn.Config(app, host=HOST, port=port, log_config=None)
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server

    if _ui_mode() == "webview":
        return _run_webview(server, server_url)

    print(f"AntiBrowser-Manager started at {server_url}", flush=True)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
