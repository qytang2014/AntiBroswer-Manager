"""Fast sing-box process launcher for speed testing and connectivity verification.

Optimized for speed testing:
- Dynamically allocates local HTTP/SOCKS ports.
- Fast readiness polling (checks port reachability every 15ms) instead of sleeping 800ms.
- Graceful and rapid process cleanup with SIGTERM/kill and temporary file unlinking.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

from backend.singbox.downloader import ensure_singbox
from backend.singbox.parser import build_singbox_config

logger = logging.getLogger("proxy_manager.singbox_runner")

_CREATE_NO_WINDOW = 0x08000000


def _find_free_port() -> int:
    """Allocate a free loopback TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_popen_kwargs() -> dict:
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


@contextlib.contextmanager
def fast_singbox_proxy(proxy_payload: Any, startup_timeout: float = 1.5) -> Iterator[str]:
    """Start a temporary sing-box instance for quick testing, waiting only until the HTTP port is ready.

    Yields the local HTTP proxy URL (e.g. 'http://127.0.0.1:54321').
    Immediately terminates and cleans up upon exiting the context.
    """
    binary = ensure_singbox()
    config = build_singbox_config(proxy_payload)

    # Bind outbound connections to physical network interface (bypassing Karing/VPN TUN)
    try:
        from backend.system_proxy_detector import get_physical_default_interface

        physical_iface = get_physical_default_interface()
        if physical_iface:
            config.setdefault("route", {})["default_interface"] = physical_iface
            for ob in config.get("outbounds", []):
                if isinstance(ob, dict) and ob.get("type") != "direct":
                    ob["bind_interface"] = physical_iface
    except Exception as exc:
        logger.debug("Failed injecting physical interface into sing-box test config: %s", exc)

    http_port = _find_free_port()
    socks_port = _find_free_port()

    config_with_inbounds = dict(config)
    config_with_inbounds["inbounds"] = [
        {
            "type": "http",
            "tag": "http-in",
            "listen": "127.0.0.1",
            "listen_port": http_port,
        },
        {
            "type": "socks",
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "listen_port": socks_port,
        },
    ]

    tmp_dir = Path(tempfile.gettempdir()) / "cloakbrowser_singbox_test"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, path_str = tempfile.mkstemp(suffix=".json", dir=tmp_dir, prefix="sb_test_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(config_with_inbounds, f, ensure_ascii=False)
    config_file = Path(path_str)

    cmd = [str(binary), "run", "-c", str(config_file)]
    proc = subprocess.Popen(cmd, **_build_popen_kwargs())

    try:
        deadline = time.monotonic() + startup_timeout
        ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                err_msg = ""
                if proc.stderr:
                    try:
                        err_msg = proc.stderr.read().decode("utf-8", errors="replace").strip()
                    except Exception:
                        pass
                detail = f": {err_msg}" if err_msg else " — the node may be malformed or unreachable."
                raise RuntimeError(f"sing-box exited immediately (code={proc.returncode}){detail}")
            try:
                with socket.create_connection(("127.0.0.1", http_port), timeout=0.03):
                    ready = True
                    break
            except OSError:
                time.sleep(0.015)

        if not ready:
            if proc.poll() is not None:
                err_msg = proc.stderr.read().decode("utf-8", errors="replace").strip() if proc.stderr else ""
                raise RuntimeError(f"sing-box exited with code {proc.returncode}: {err_msg}")
            raise TimeoutError(f"sing-box failed to start within {startup_timeout}s")

        yield f"http://127.0.0.1:{http_port}"
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=0.5)
        except Exception as exc:
            logger.debug("Error terminating test sing-box process: %s", exc)
        finally:
            config_file.unlink(missing_ok=True)
