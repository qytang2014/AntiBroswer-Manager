"""Host runtime policy and platform-specific Manager paths."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

HostOS = Literal["windows", "macos", "linux"]
RuntimeMode = Literal["native", "docker"]
ViewerMode = Literal["native-window", "vnc"]

_RUNTIME_ENV = "CLOAKBROWSER_MANAGER_RUNTIME"
_DATA_DIR_ENV = "CLOAKBROWSER_MANAGER_DATA_DIR"
_LEGACY_DATA_DIR_ENVS = ("CLOAKBROWSER_DATA_DIR",)


@dataclass(frozen=True)
class RuntimeConfig:
    host_os: HostOS
    runtime_mode: RuntimeMode
    viewer_mode: ViewerMode
    data_dir: Path

    @property
    def is_native(self) -> bool:
        return self.runtime_mode == "native"


def bundle_dir() -> Path:
    """Root for bundled resources (frontend/dist, data files).

    Under a PyInstaller/Nuitka freeze, resources are extracted to a temp dir
    exposed as ``sys._MEIPASS``; running from source they sit one level above
    the ``backend`` package (the manager repo root).
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def detect_host_os(platform_name: str | None = None) -> HostOS:
    """Map Python's platform identifier to Manager's supported hosts."""
    value = platform_name or sys.platform
    if value == "win32":
        return "windows"
    if value == "darwin":
        return "macos"
    if value.startswith("linux"):
        return "linux"
    raise RuntimeError(f"Unsupported operating system: {value}")


def default_data_dir(
    host_os: HostOS,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the Manager state directory without creating it."""
    env = os.environ if environ is None else environ
    configured = env.get(_DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser()

    for legacy_name in _LEGACY_DATA_DIR_ENVS:
        legacy_value = env.get(legacy_name)
        if legacy_value:
            return Path(legacy_value).expanduser()

    user_home = home or Path.home()
    if host_os == "windows":
        local_app_data = env.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return base / "AntiBrowser-Manager"
    if host_os == "macos":
        return user_home / "Library" / "Application Support" / "AntiBrowser-Manager"
    return Path("/data")


def resolve_runtime(
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> RuntimeConfig:
    """Resolve the only supported runtime for the current host."""
    env = os.environ if environ is None else environ
    host_os = detect_host_os(platform_name)
    default_mode: RuntimeMode = "docker" if host_os == "linux" else "native"
    requested_mode = env.get(_RUNTIME_ENV, default_mode).strip().lower()
    if requested_mode not in {"native", "docker"}:
        raise RuntimeError(
            f"{_RUNTIME_ENV} must be 'native' or 'docker', got {requested_mode!r}"
        )

    runtime_mode = cast(RuntimeMode, requested_mode)
    if host_os == "linux" and runtime_mode != "docker":
        raise RuntimeError(
            "Native Linux desktop mode is not supported; run Manager with Docker/KasmVNC"
        )
    if host_os != "linux" and runtime_mode != "native":
        raise RuntimeError(
            f"Docker runtime is supported only on Linux, not {host_os}"
        )

    viewer_mode: ViewerMode = "vnc" if runtime_mode == "docker" else "native-window"
    cfg = RuntimeConfig(
        host_os=host_os,
        runtime_mode=runtime_mode,
        viewer_mode=viewer_mode,
        data_dir=default_data_dir(host_os, env, home),
    )
    patch_kernel_data_dirs(cfg.data_dir)
    return cfg


def patch_kernel_data_dirs(data_dir: Path) -> None:
    """Ensure CloakBrowser and Camoufox use data_dir/kernels instead of polluting ~/.

    Redirects:
      ~/.cloakbrowser -> data_dir/kernels/cloakbrowser
      Camoufox cache  -> data_dir/kernels/camoufox
    """
    cloak_dir = data_dir / "kernels" / "cloakbrowser"
    camou_dir = data_dir / "kernels" / "camoufox"
    try:
        cloak_dir.mkdir(parents=True, exist_ok=True)
        camou_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    os.environ["CLOAKBROWSER_CACHE_DIR"] = str(cloak_dir)
    os.environ["CAMOUFOX_DATA_DIR"] = str(camou_dir)

    # Monkey patch platformdirs for camoufox
    try:
        import platformdirs
        _orig_user_cache_dir = getattr(platformdirs, "_orig_user_cache_dir", platformdirs.user_cache_dir)
        platformdirs._orig_user_cache_dir = _orig_user_cache_dir
        def _custom_user_cache_dir(appname=None, *args, **kwargs):
            if appname == "camoufox":
                return str(camou_dir)
            return _orig_user_cache_dir(appname, *args, **kwargs)
        platformdirs.user_cache_dir = _custom_user_cache_dir
    except Exception:
        pass

    # Monkey patch cloakbrowser config and license
    try:
        import cloakbrowser.config as c_cfg
        c_cfg.get_cache_dir = lambda: cloak_dir
    except Exception:
        pass

    try:
        import cloakbrowser.license as c_lic
        import uuid

        def _custom_mint_denial_file() -> str | None:
            try:
                denial_dir = cloak_dir / "denials"
                denial_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return None
            try:
                c_lic._sweep_stale_denials(denial_dir)
            except Exception:
                pass
            return str(denial_dir / f"{uuid.uuid4().hex}.json")

        c_lic.mint_denial_file = _custom_mint_denial_file
    except Exception:
        pass

    # Clean up empty or legacy ~/.cloakbrowser
    try:
        home_cb = Path.home() / ".cloakbrowser"
        if home_cb.exists() and home_cb.is_dir():
            sub_items = list(home_cb.iterdir())
            non_stale = [i for i in sub_items if i.name not in ("denials", "license.key") and not i.name.startswith(".")]
            if not non_stale:
                old_key = home_cb / "license.key"
                if old_key.exists() and not (cloak_dir / "license.key").exists():
                    import shutil
                    shutil.copy2(old_key, cloak_dir / "license.key")
                import shutil
                shutil.rmtree(home_cb, ignore_errors=True)
    except Exception:
        pass
