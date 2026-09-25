"""Sing-box process management.

Handles:
  - Isolated port allocation (race-free via socket binding)
  - Cross-platform process spawning (Windows: CREATE_NO_WINDOW,
    Linux: prctl PDEATHSIG, macOS: standard SIGTERM)
  - Temp config file lifecycle (one file per process, cleaned on terminate)
  - Startup health check (brief wait + poll)
  - Graceful and forced termination
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import platform
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("backend.singbox")

# Windows process creation flag: hide the console window
_CREATE_NO_WINDOW = 0x08000000

# How long to wait (seconds) after spawn before polling for early exit
_STARTUP_WAIT = 0.8

# Registry of all live SingboxProcess instances — used by atexit cleanup
_live_processes: list["SingboxProcess"] = []
_registry_lock = threading.Lock()


def _atexit_cleanup() -> None:
    """Best-effort cleanup of all running sing-box processes on interpreter exit."""
    with _registry_lock:
        procs = list(_live_processes)
    for proc in procs:
        try:
            proc.terminate()
        except Exception:
            pass


atexit.register(_atexit_cleanup)


# ---------------------------------------------------------------------------
# Port allocation
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Ask the OS to allocate a free TCP port on loopback, then release it.

    The port is returned immediately. The caller must start listening before
    another process can claim it — sing-box startup is fast enough that this
    window is negligible in practice. Using port 0 guarantees no collision even
    under high concurrency (each call gets a unique kernel-allocated port).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Process dataclass
# ---------------------------------------------------------------------------

@dataclass
class SingboxProcess:
    """Represents a running sing-box instance tied to a browser session.

    Attributes:
        proc:        The underlying subprocess.Popen object.
        socks_port:  Local SOCKS5 port that sing-box listens on.
        http_port:   Local HTTP proxy port that sing-box listens on.
        config_file: Path to the temporary config JSON (deleted on terminate).
    """

    proc: subprocess.Popen
    socks_port: int
    http_port: int
    config_file: Path
    _terminated: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        with _registry_lock:
            _live_processes.append(self)

    @property
    def socks5_url(self) -> str:
        """SOCKS5 proxy URL pointing to the local sing-box inbound."""
        return f"socks5://127.0.0.1:{self.socks_port}"

    @property
    def http_url(self) -> str:
        """HTTP proxy URL pointing to the local sing-box inbound."""
        return f"http://127.0.0.1:{self.http_port}"

    @property
    def is_running(self) -> bool:
        """Return True if the sing-box process is still alive."""
        return self.proc.poll() is None

    def terminate(self) -> None:
        """Terminate the sing-box process and remove the temporary config file.

        Safe to call multiple times. Attempts a graceful SIGTERM first; if the
        process does not exit within 3 seconds, escalates to SIGKILL / kill().
        """
        if self._terminated:
            return
        self._terminated = True

        with _registry_lock:
            try:
                _live_processes.remove(self)
            except ValueError:
                pass

        # Graceful termination
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logger.warning("sing-box did not exit in 3s after SIGTERM; force-killing.")
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=2)
                except Exception as exc:
                    logger.error("Failed to force-kill sing-box (pid=%d): %s", self.proc.pid, exc)
            except Exception as exc:
                logger.debug("Error during sing-box terminate: %s", exc)

        # Remove temp config file
        try:
            self.config_file.unlink(missing_ok=True)
        except Exception:
            pass

        logger.debug("sing-box process %d terminated.", self.proc.pid)


# ---------------------------------------------------------------------------
# Cross-platform process launch
# ---------------------------------------------------------------------------

def _make_preexec_fn():
    """Return a preexec_fn for Linux that sets PDEATHSIG = SIGTERM.

    When the parent Python process dies (even via kill -9), the kernel will
    automatically send SIGTERM to the sing-box child process.
    Returns None on non-Linux platforms.
    """
    if platform.system() != "Linux":
        return None

    try:
        import ctypes
        import ctypes.util

        libc_name = ctypes.util.find_library("c")
        if libc_name is None:
            return None
        libc = ctypes.CDLL(libc_name, use_errno=True)
        PR_SET_PDEATHSIG = 1
        SIGTERM = 15

        def _set_pdeathsig() -> None:
            libc.prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0)

        return _set_pdeathsig
    except Exception as exc:
        logger.debug("Could not set up PDEATHSIG (will rely on atexit): %s", exc)
        return None


def _build_popen_kwargs() -> dict:
    """Return platform-specific kwargs for subprocess.Popen."""
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }

    system = platform.system()
    if system == "Windows":
        # Hide the console window that would otherwise flash on screen
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    else:
        preexec = _make_preexec_fn()
        if preexec is not None:
            kwargs["preexec_fn"] = preexec

    return kwargs


# ---------------------------------------------------------------------------
# Temp config file management
# ---------------------------------------------------------------------------

def _get_config_tmp_dir() -> Path:
    """Return (and create) the directory for temporary sing-box config files."""
    d = Path(tempfile.gettempdir()) / "antibrowser_singbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_temp_config(config: dict) -> Path:
    """Write a sing-box config dict to a temp JSON file and return its path."""
    tmp_dir = _get_config_tmp_dir()
    # Use delete=False so we control the lifecycle ourselves
    fd, path_str = tempfile.mkstemp(suffix=".json", dir=tmp_dir, prefix="sbcfg_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
    except Exception:
        os.close(fd)
        raise
    return Path(path_str)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_singbox(binary: Path, config: dict) -> SingboxProcess:
    """Start a sing-box process with isolated ports and return a SingboxProcess.

    The config dict is expected to have been built by parser.build_singbox_config().
    This function injects the socks5 and http inbounds with runtime-allocated ports
    before writing the final config file.

    Args:
        binary: Absolute path to the sing-box executable.
        config: Sing-box config dict (without inbounds — injected here).

    Returns:
        SingboxProcess representing the live sing-box instance.

    Raises:
        RuntimeError: If sing-box exits immediately after launch (bad config).
    """
    socks_port = _find_free_port()
    http_port  = _find_free_port()

    # Inject inbounds with the dynamically allocated ports
    config_with_inbounds = dict(config)
    config_with_inbounds["inbounds"] = [
        {
            "type": "socks",
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "listen_port": socks_port,
        },
        {
            "type": "http",
            "tag": "http-in",
            "listen": "127.0.0.1",
            "listen_port": http_port,
        },
    ]

    config_file = _write_temp_config(config_with_inbounds)

    cmd = [str(binary), "run", "-c", str(config_file)]
    logger.debug(
        "Starting sing-box: socks=%d http=%d config=%s",
        socks_port, http_port, config_file,
    )

    try:
        proc = subprocess.Popen(cmd, **_build_popen_kwargs())
    except Exception as exc:
        config_file.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to start sing-box: {exc}") from exc

    # Brief wait for early exit detection
    time.sleep(_STARTUP_WAIT)
    if proc.poll() is not None:
        config_file.unlink(missing_ok=True)
        err_msg = ""
        if proc.stderr:
            try:
                err_msg = proc.stderr.read().decode("utf-8", errors="replace").strip()
            except Exception:
                pass
        detail = f": {err_msg}" if err_msg else " — the node may be malformed or unreachable."
        raise RuntimeError(
            f"sing-box exited immediately (code={proc.returncode}){detail}"
        )

    logger.debug(
        "sing-box started (pid=%d): socks5=127.0.0.1:%d http=127.0.0.1:%d",
        proc.pid, socks_port, http_port,
    )

    return SingboxProcess(
        proc=proc,
        socks_port=socks_port,
        http_port=http_port,
        config_file=config_file,
    )
