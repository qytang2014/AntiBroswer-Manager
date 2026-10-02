"""backend.singbox — Sing-box proxy manager for CloakBrowser.

Provides sing-box protocol support (VLESS, VMess, Trojan, Shadowsocks,
Hysteria2, etc.) as an extension to the standard SOCKS5/HTTP proxy options.

Public surface:
    is_singbox_proxy(proxy)        -> bool
    handle_singbox_proxy(proxy)    -> (SingboxProcess | None, str | None, str | None)
    SingboxProcess                 -> dataclass for a live sing-box instance
    ensure_singbox()               -> Path  (binary resolver)
    build_singbox_config(input)    -> dict  (config builder)
    resolve_profile_proxy(...)     -> Any   (profile persistence)

Usage within browser.py (hook points):

    # 1. In _resolve_proxy_config():
    from .singbox.manager import handle_singbox_proxy
    _singbox_proc, _local_url, _http_url = handle_singbox_proxy(proxy)
    if _local_url:
        proxy = _local_url   # replace with local socks5://127.0.0.1:port

    # 2. In _close_with_cleanup():
    if _singbox_proc is not None:
        _singbox_proc.terminate()
"""

from .downloader import ensure_singbox
from .manager import handle_singbox_proxy, is_singbox_proxy
from .parser import build_singbox_config
from .process import SingboxProcess
from .profile import load_profile_proxy, resolve_profile_proxy, save_profile_proxy

__all__ = [
    "ensure_singbox",
    "handle_singbox_proxy",
    "is_singbox_proxy",
    "build_singbox_config",
    "SingboxProcess",
    "resolve_profile_proxy",
    "save_profile_proxy",
    "load_profile_proxy",
]
