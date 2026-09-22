"""Start CloakBrowser Manager natively on Windows or macOS."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
LEGACY_SETUP_MARKER = VENV_DIR / ".manager-setup.json"
FRONTEND_MARKER = VENV_DIR / ".manager-frontend.json"
FRONTEND_DIR = ROOT / "frontend"
SERVER_URL = "http://127.0.0.1:8080"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_setup_state() -> dict[str, str]:
    try:
        value = json.loads(FRONTEND_MARKER.read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _find_or_install_uv() -> str:
    """Locate or guide the installation of the uv package manager."""
    uv_bin = "uv.exe" if os.name == "nt" else "uv"
    uv_path = shutil.which(uv_bin)
    if uv_path:
        return uv_path

    common_paths = [
        Path.home() / ".local" / "bin" / uv_bin,
        Path.home() / ".cargo" / "bin" / uv_bin,
    ]
    for p in common_paths:
        if p.is_file() and os.access(p, os.X_OK):
            os.environ["PATH"] = f"{p.parent}{os.pathsep}{os.environ.get('PATH', '')}"
            return str(p)

    print("[setup] 'uv' is required to manage dependencies and start CloakBrowser Manager.", flush=True)

    if os.name == "nt":
        install_cmd = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    else:
        install_cmd = "curl -LsSf https://astral.sh/uv/install.sh | sh"

    should_install = False
    if sys.stdin.isatty():
        try:
            choice = input("[setup] Would you like to automatically install uv now? [Y/n]: ").strip().lower()
            should_install = choice in {"", "y", "yes"}
        except (EOFError, KeyboardInterrupt):
            print("\n[setup] Installation cancelled by user.", flush=True)
            should_install = False

    if should_install:
        print(f"[setup] Running: {install_cmd}", flush=True)
        try:
            subprocess.run(install_cmd, shell=True, check=True)
            for p in common_paths:
                if p.is_file() and os.access(p, os.X_OK):
                    os.environ["PATH"] = f"{p.parent}{os.pathsep}{os.environ.get('PATH', '')}"
                    return str(p)
            found = shutil.which(uv_bin)
            if found:
                return found
        except Exception as exc:
            print(f"[error] Automated installation of uv failed: {exc}", file=sys.stderr, flush=True)

    raise RuntimeError(
        "'uv' is required to manage dependencies.\n"
        f"Please install it manually:\n  {install_cmd}\n"
        "Or see: https://docs.astral.sh/uv/getting-started/installation/"
    )


def _run(command: list[str], cwd: Path = ROOT) -> None:
    print(f"[setup] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _ensure_environment() -> Path:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required")
    if sys.platform not in {"win32", "darwin"}:
        raise RuntimeError(
            "Native Manager supports Windows and macOS; use Docker on Linux"
        )

    # Clean legacy pip virtual environment if detected
    if LEGACY_SETUP_MARKER.exists():
        print("[setup] Detected legacy pip environment; resetting .venv for uv", flush=True)
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    uv_path = _find_or_install_uv()
    _run([uv_path, "sync", "--no-dev"])

    python = _venv_python()
    if not python.exists():
        raise RuntimeError(f"Virtual environment python binary not found at {python}")

    state = _load_setup_state()
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("Node.js 18 or newer is required to build the Manager UI")

    package_lock = FRONTEND_DIR / "package-lock.json"
    frontend_hash = _file_hash(package_lock)
    if state.get("frontend") != frontend_hash or not (FRONTEND_DIR / "node_modules").exists():
        _run([npm, "ci"], cwd=FRONTEND_DIR)
        state["frontend"] = frontend_hash

    source_mtime = max(
        path.stat().st_mtime
        for path in (FRONTEND_DIR / "src").rglob("*")
        if path.is_file()
    )
    index_path = FRONTEND_DIR / "dist" / "index.html"
    if not index_path.exists() or index_path.stat().st_mtime < source_mtime:
        _run([npm, "run", "build"], cwd=FRONTEND_DIR)

    FRONTEND_MARKER.write_text(json.dumps(state, indent=2))
    return python


def _ensure_server_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        try:
            server_socket.bind(("127.0.0.1", 8080))
        except OSError as exc:
            raise RuntimeError(
                "Port 8080 is already in use; stop the existing Manager or service"
            ) from exc


def main() -> int:
    try:
        python = _ensure_environment()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1

    try:
        _ensure_server_port_available()
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1

    env = {**os.environ, "CLOAKBROWSER_MANAGER_RUNTIME": "native"}
    print(f"[start] CloakBrowser Manager: {SERVER_URL}", flush=True)
    # Replace this bootstrap process with app_entry.py under the venv python.
    # os.execve hands off entirely — no lingering parent, no wrapper-of-wrapper —
    # so a dev run becomes the exact same in-process server + native webview
    # window as the frozen build (which runs app_entry.py directly). app_entry
    # opens the window, or a browser tab if pywebview is missing; set
    # CLOAKBROWSER_MANAGER_UI=browser to force a tab. execve only returns (raises)
    # on failure, so anything below is the error path.
    os.chdir(ROOT)
    os.execve(str(python), [str(python), str(ROOT / "app_entry.py")], env)
    return 1  # unreachable unless execve failed


if __name__ == "__main__":
    raise SystemExit(main())
