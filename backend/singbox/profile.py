"""Profile-level proxy persistence for sing-box.

Reads and writes a 'proxy.json' file inside a persistent browser profile
directory (user_data_dir). This allows each profile to carry its own proxy
configuration so that a re-launch without explicit proxy= argument can
transparently reuse the last setting.

File format (proxy.json):
    {
      "type": "singbox",
      "config": "<vless://...>"   OR
      "config": {"outbounds": [...]}
    }

Design notes:
  - The file is written only when the user explicitly passes a proxy arg.
  - On read, the file is treated as a hint; errors are logged and silently
    skipped so a corrupt proxy.json never prevents the profile from loading.
  - Standard HTTP/SOCKS proxies are also stored here for portability.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend.singbox")

_PROXY_FILENAME = "proxy.json"


def save_profile_proxy(user_data_dir: str | Path, proxy: Any) -> None:
    """Persist the proxy configuration inside the profile directory.

    Args:
        user_data_dir: The persistent browser profile directory.
        proxy:         The proxy value as passed to launch_persistent_context().
                       Can be a string URL, a ProxySettings dict, or a sing-box
                       config dict.  None is a no-op (no file written).
    """
    if proxy is None:
        return

    profile_dir = Path(user_data_dir)
    proxy_file = profile_dir / _PROXY_FILENAME

    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        proxy_file.write_text(
            json.dumps(proxy, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("Saved proxy config to profile: %s", proxy_file)
    except Exception as exc:
        logger.warning("Could not save proxy config to profile '%s': %s", proxy_file, exc)


def load_profile_proxy(user_data_dir: str | Path) -> Any:
    """Load the proxy configuration from the profile directory, if present.

    Args:
        user_data_dir: The persistent browser profile directory.

    Returns:
        The stored proxy value (str, dict, or None if absent/unreadable).
    """
    proxy_file = Path(user_data_dir) / _PROXY_FILENAME

    if not proxy_file.exists():
        return None

    try:
        data = json.loads(proxy_file.read_text(encoding="utf-8"))
        logger.debug("Loaded proxy config from profile: %s", proxy_file)
        return data
    except Exception as exc:
        logger.warning(
            "Could not read proxy config from '%s' (ignoring): %s", proxy_file, exc
        )
        return None


def resolve_profile_proxy(user_data_dir: str | Path | None, explicit_proxy: Any) -> Any:
    """Resolve the effective proxy for a persistent context launch.

    Priority:
      1. Explicit proxy passed by the caller (always wins).
      2. Stored proxy.json in the profile dir (auto-reuse).
      3. None (no proxy).

    If an explicit proxy is provided and differs from the stored one, the
    profile is updated so future launches re-use the new setting.

    Args:
        user_data_dir:  Profile directory (may be None for non-persistent calls).
        explicit_proxy: The proxy value from the launch call (may be None).

    Returns:
        The effective proxy value to use for this launch.
    """
    if user_data_dir is None:
        return explicit_proxy

    if explicit_proxy is not None:
        # Persist for next launch
        save_profile_proxy(user_data_dir, explicit_proxy)
        return explicit_proxy

    # No explicit proxy — check if the profile has a saved one
    return load_profile_proxy(user_data_dir)
