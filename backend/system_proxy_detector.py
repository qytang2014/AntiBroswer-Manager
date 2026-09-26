"""Detect OS-level proxy and VPN state for informational display."""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import time
from typing import TypedDict

logger = logging.getLogger("proxy_manager.system_proxy")


class SystemProxyStatus(TypedDict):
    active: bool  # Any proxy/VPN detected
    tun_mode: bool  # TUN/VPN network extension active
    http_proxy: str | None  # e.g. "127.0.0.1:7890"
    detected_app: str | None  # e.g. "Karing", "Clash", "V2RayN"


_KNOWN_TUN_APPS: list[tuple[str, str]] = [
    ("karing", "Karing"),
    ("clash", "Clash"),
    ("clashx", "ClashX"),
    ("surge", "Surge"),
    ("quantumult", "Quantumult X"),
    ("v2rayu", "V2rayU"),
    ("v2ray", "V2Ray"),
    ("mihomo", "Mihomo"),
    ("shadowrocket", "Shadowrocket"),
    ("loon", "Loon"),
    ("stash", "Stash"),
]

# Simple in-memory cache to avoid spawning subprocesses too frequently (3s TTL)
_STATUS_CACHE: tuple[float, SystemProxyStatus] | None = None
_CACHE_TTL_SECONDS = 3.0


def get_system_proxy_status(force: bool = False) -> SystemProxyStatus:
    """Detect macOS system proxy + active TUN VPN connections.

    Checks:
    1. System HTTP/HTTPS/SOCKS proxy via scutil --proxy
    2. Active VPN connection services via scutil --nc list (* (Connected))
    3. Primary network interface via route get default (detects utun)
    4. Running proxy processes via ps -A

    Safely fails open with all False/None on unsupported OS or command errors.
    """
    global _STATUS_CACHE
    now = time.monotonic()
    if not force and _STATUS_CACHE is not None:
        cached_time, cached_val = _STATUS_CACHE
        if now - cached_time < _CACHE_TTL_SECONDS:
            return dict(cached_val)  # return shallow copy

    result: SystemProxyStatus = {
        "active": False,
        "tun_mode": False,
        "http_proxy": None,
        "detected_app": None,
    }

    if platform.system() != "Darwin":
        _STATUS_CACHE = (now, result)
        return result

    # 1. Check macOS system HTTP/HTTPS/SOCKS proxy via scutil
    has_system_proxy = False
    try:
        out = subprocess.check_output(
            ["scutil", "--proxy"], timeout=2.0, text=True, stderr=subprocess.DEVNULL
        )
        http_enable = re.search(r"HTTPEnable\s*:\s*1", out)
        http_proxy = re.search(r"HTTPProxy\s*:\s*(\S+)", out)
        http_port = re.search(r"HTTPPort\s*:\s*(\d+)", out)
        if http_enable and http_proxy and http_port:
            result["http_proxy"] = f"{http_proxy.group(1)}:{http_port.group(1)}"
            has_system_proxy = True

        if not result["http_proxy"]:
            https_enable = re.search(r"HTTPSEnable\s*:\s*1", out)
            https_proxy = re.search(r"HTTPSProxy\s*:\s*(\S+)", out)
            https_port = re.search(r"HTTPSPort\s*:\s*(\d+)", out)
            if https_enable and https_proxy and https_port:
                result["http_proxy"] = f"{https_proxy.group(1)}:{https_port.group(1)}"
                has_system_proxy = True

        if not result["http_proxy"]:
            socks_enable = re.search(r"SOCKSEnable\s*:\s*1", out)
            socks_proxy = re.search(r"SOCKSProxy\s*:\s*(\S+)", out)
            socks_port = re.search(r"SOCKSPort\s*:\s*(\d+)", out)
            if socks_enable and socks_proxy and socks_port:
                result["http_proxy"] = f"socks5://{socks_proxy.group(1)}:{socks_port.group(1)}"
                has_system_proxy = True
    except Exception as exc:
        logger.debug("Failed checking scutil --proxy: %s", exc)

    # 2. Check running proxy/VPN processes
    detected_proc_app: str | None = None
    try:
        ps_out = subprocess.check_output(
            ["ps", "-A", "-o", "comm="],
            timeout=2.0,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        ps_lower = ps_out.lower()
        for keyword, app_name in _KNOWN_TUN_APPS:
            if keyword in ps_lower:
                detected_proc_app = app_name
                break
    except Exception as exc:
        logger.debug("Failed checking running proxy processes: %s", exc)

    # 3. Check for active VPN connections in macOS Network Connections
    has_connected_vpn = False
    vpn_app_name: str | None = None
    try:
        nc_out = subprocess.check_output(
            ["scutil", "--nc", "list"],
            timeout=2.0,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in nc_out.splitlines():
            sline = line.strip()
            if sline.startswith("* (Connected)"):
                has_connected_vpn = True
                m = re.search(r'"([^"]+)"', sline)
                if m:
                    raw_name = m.group(1)
                    # Clean up e.g. "Karing (system)" -> "Karing"
                    vpn_app_name = raw_name.split("(")[0].strip() or raw_name
                break
    except Exception as exc:
        logger.debug("Failed checking scutil --nc list: %s", exc)

    # 4. Check primary default network interface
    default_iface: str | None = None
    try:
        route_out = subprocess.check_output(
            ["route", "-n", "get", "default"],
            timeout=2.0,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        m = re.search(r"interface:\s*(\S+)", route_out)
        if m:
            default_iface = m.group(1).strip()
    except Exception as exc:
        logger.debug("Failed checking default route: %s", exc)

    # Determine TUN mode
    is_tun_active = has_connected_vpn or bool(default_iface and default_iface.startswith("utun"))

    if is_tun_active:
        result["active"] = True
        result["tun_mode"] = True
        result["detected_app"] = detected_proc_app or vpn_app_name or "VPN"
    elif has_system_proxy:
        result["active"] = True
        result["tun_mode"] = False
        result["detected_app"] = detected_proc_app or "系统代理"
    else:
        # Neither TUN interface nor system proxy is routing traffic
        result["active"] = False
        result["tun_mode"] = False
        result["detected_app"] = None

    _STATUS_CACHE = (now, result)
    return result
