"""Sing-box proxy manager — public entry point for browser.py integration.

This module is the sole interface between cloakbrowser/browser.py and the
sing-box subsystem. browser.py calls handle_singbox_proxy() at one point and
receives either (None, None) — meaning "pass through, nothing to do" — or
(SingboxProcess, local_socks5_url) — meaning "replace proxy with this URL
and terminate the process when the browser closes".

All heavy logic (download, parse, spawn) is delegated to the sub-modules.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("backend.singbox")


def is_singbox_proxy(proxy: Any) -> bool:
    """Return True if the proxy value requests a sing-box connection.

    A sing-box proxy is recognised as a dict with ``"type": "singbox"``.
    Any other value (str URL, standard ProxySettings dict, None) is left
    untouched by this subsystem.
    """
    return isinstance(proxy, dict) and proxy.get("type") == "singbox"


def handle_singbox_proxy(
    proxy: Any,
) -> tuple["SingboxProcess | None", str | None, str | None]:  # noqa: F821
    """Start sing-box if proxy is a sing-box config; otherwise pass through.

    Called from browser.py's _resolve_proxy_config (and equivalents) before
    the standard proxy resolution logic runs.

    Args:
        proxy: The raw proxy argument passed by the user.

    Returns:
        (singbox_proc, local_socks5_url, local_http_url)
          - If proxy is a sing-box dict: returns the live process and its
            local SOCKS5 URL and HTTP URL.
          - Otherwise: returns (None, None, None).

    Raises:
        RuntimeError: If sing-box binary is unavailable or fails to start.
        ValueError:   If the supplied node config is malformed.
    """
    if not is_singbox_proxy(proxy):
        return None, None, None

    from .downloader import ensure_singbox
    from .parser import build_singbox_config
    from .process import SingboxProcess, start_singbox

    logger.debug("sing-box proxy detected — resolving binary and config.")

    binary = ensure_singbox()
    config = build_singbox_config(proxy)
    proc = start_singbox(binary, config)

    logger.info(
        "sing-box started on socks5://127.0.0.1:%d (pid=%d)",
        proc.socks_port, proc.proc.pid,
    )

    return proc, proc.socks5_url, proc.http_url
