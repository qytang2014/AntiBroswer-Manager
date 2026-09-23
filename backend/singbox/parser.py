"""Sing-box configuration parser.

Converts three supported input formats into a valid sing-box configuration dict:

  1. Single proxy node URI  — vless://, vmess://, trojan://, ss://, hysteria2://
  2. Subscription URL       — http(s):// pointing to a Base64-encoded node list
  3. Native JSON dict       — {"outbounds": [...]} passed directly through

The resulting config dict is then augmented with inbounds (socks5 + http)
and a routing table by process.py at launch time.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger("backend.singbox")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_singbox_config(config_input: str | dict[str, Any]) -> dict[str, Any]:
    """Convert a user-supplied proxy config into a sing-box config dict.

    Accepted input forms:
      - str starting with a proxy scheme (vless://, vmess://, trojan://, etc.)
        -> single outbound node
      - str starting with http:// or https://
        -> treat as subscription URL (fetches and Base64-decodes the node list)
      - dict with an "outbounds" key
        -> used verbatim as the outbounds list; inbounds/route added by caller
      - dict with a "config" key
        -> same as passing config_input["config"] directly

    Returns:
        A sing-box config dict without inbounds (injected at process start).

    Raises:
        TypeError: On unsupported input types.
        ValueError: On unparseable URI schemes.
    """
    # Allow {"config": ..., "type": "singbox"} wrappers
    while isinstance(config_input, dict) and "config" in config_input:
        config_input = config_input["config"]

    if isinstance(config_input, dict):
        if "outbounds" in config_input:
            return _wrap_outbounds(config_input["outbounds"])
        raise ValueError(
            "Sing-box config dict must have an 'outbounds' key. "
            f"Got keys: {list(config_input.keys())}"
        )

    if isinstance(config_input, str):
        config_input = config_input.strip()
        scheme = urlparse(config_input).scheme.lower()
        if scheme in ("http", "https"):
            return _parse_subscription(config_input)
        return _wrap_outbounds([_parse_uri(config_input)])

    raise TypeError(
        f"Unsupported sing-box config type: {type(config_input).__name__}. "
        "Expected a proxy URI string, subscription URL, or outbounds dict."
    )


# ---------------------------------------------------------------------------
# Subscription handling
# ---------------------------------------------------------------------------

def _parse_subscription(url: str) -> dict[str, Any]:
    """Fetch a subscription URL and parse all node links inside it.

    Supports:
      - Pure Base64-encoded list (one URI per line after decoding)
      - Plain-text list (one URI per line, no Base64)

    Returns a sing-box config dict with all parsed outbounds.
    """
    import httpx

    logger.info("Fetching subscription from: %s", url)
    try:
        resp = httpx.get(url, timeout=httpx.Timeout(30.0), follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        # Retry with trust_env=False in case system/corporate proxy blocked it
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=True, trust_env=False) as client:
                resp = client.get(url)
                resp.raise_for_status()
        except Exception:
            raise RuntimeError(f"Failed to fetch subscription URL '{url}': {exc}") from exc

    raw = resp.text.strip()

    # Attempt Base64 decode; fall back to treating as plain text
    try:
        # Fix padding before decode
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.b64decode(padded).decode("utf-8").strip()
    except Exception:
        decoded = raw

    links = [line.strip() for line in decoded.splitlines() if line.strip()]
    if not links:
        raise ValueError(f"Subscription returned no node links: {url}")

    outbounds = []
    for link in links:
        try:
            outbounds.append(_parse_uri(link))
        except (ValueError, NotImplementedError) as exc:
            logger.warning("Skipping unparseable node '%s...': %s", link[:40], exc)

    if not outbounds:
        raise ValueError(
            f"Subscription '{url}' contained {len(links)} links but none could be parsed. "
            "Consider passing a complete sing-box outbounds JSON instead."
        )

    logger.info("Parsed %d node(s) from subscription.", len(outbounds))
    return _wrap_outbounds(outbounds)


# ---------------------------------------------------------------------------
# URI dispatch
# ---------------------------------------------------------------------------

def _parse_uri(uri: str) -> dict[str, Any]:
    """Dispatch a proxy URI to the appropriate parser.

    Returns a sing-box outbound dict.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    dispatch: dict[str, Any] = {
        "vless":       _parse_vless,
        "vmess":       _parse_vmess,
        "trojan":      _parse_trojan,
        "trojan-go":   _parse_trojan,
        "ss":          _parse_shadowsocks,
        "shadowsocks": _parse_shadowsocks,
        "hysteria":    _parse_hysteria,
        "hysteria2":   _parse_hysteria2,
        "hy2":         _parse_hysteria2,
        "tuic":        _parse_tuic,
        "anytls":      _parse_anytls,
    }

    parser = dispatch.get(scheme)
    if parser is None:
        raise ValueError(
            f"Unsupported proxy URI scheme: '{scheme}'. "
            "Supported: vless, vmess, trojan, ss, hysteria, hysteria2, tuic, anytls. "
            "For other protocols, pass a complete sing-box outbounds JSON."
        )

    return parser(uri)


# ---------------------------------------------------------------------------
# Protocol parsers
# ---------------------------------------------------------------------------

def _slug(tag: str) -> str:
    """Sanitize a node tag for use as a sing-box outbound tag."""
    return re.sub(r"[^\w\-.]", "_", tag)[:64] or "node"


def _parse_vless(uri: str) -> dict[str, Any]:
    """Parse a VLESS URI into a sing-box outbound.

    Format: vless://<uuid>@<host>:<port>?<params>#<tag>
    """
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)

    def _p(key: str, default: str = "") -> str:
        return params.get(key, [default])[0]

    tag = unquote(parsed.fragment) if parsed.fragment else "vless-node"
    uuid = parsed.username or ""
    host = parsed.hostname or ""
    port = parsed.port or 443

    transport_type = _p("type", "tcp")
    security = _p("security", "none")

    outbound: dict[str, Any] = {
        "type": "vless",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "uuid": uuid,
        "flow": _p("flow"),
    }

    # TLS / Reality
    if security in ("tls", "reality"):
        tls: dict[str, Any] = {
            "enabled": True,
            "server_name": _p("sni") or _p("host") or host,
        }
        if security == "reality":
            tls["reality"] = {
                "enabled": True,
                "public_key": _p("pbk"),
                "short_id": _p("sid"),
            }
        fp = _p("fp")
        if fp:
            tls["utls"] = {"enabled": True, "fingerprint": fp}
        outbound["tls"] = tls

    # Transport
    if transport_type != "tcp":
        outbound["transport"] = _build_transport(transport_type, params, host)

    return outbound


def _parse_vmess(uri: str) -> dict[str, Any]:
    """Parse a VMess URI (Base64-encoded JSON) into a sing-box outbound.

    Format: vmess://<base64(json)>
    """
    raw = uri[len("vmess://"):]
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(base64.b64decode(padded).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot decode VMess URI: {exc}") from exc

    tag = data.get("ps") or data.get("add") or "vmess-node"
    host = data.get("add", "")
    port = int(data.get("port", 443))
    tls_enabled = str(data.get("tls", "")).lower() == "tls"
    net = data.get("net", "tcp")

    outbound: dict[str, Any] = {
        "type": "vmess",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "uuid": data.get("id", ""),
        "security": data.get("scy") or data.get("cipher") or "auto",
        "alter_id": int(data.get("aid", 0)),
    }

    if tls_enabled:
        outbound["tls"] = {
            "enabled": True,
            "server_name": data.get("sni") or data.get("host") or host,
        }

    params: dict[str, list[str]] = {}
    if data.get("host"):
        params["host"] = [data["host"]]
    if data.get("path"):
        params["path"] = [data["path"]]

    if net != "tcp":
        outbound["transport"] = _build_transport(net, params, host)

    return outbound


def _parse_trojan(uri: str) -> dict[str, Any]:
    """Parse a Trojan / Trojan-Go URI into a sing-box outbound.

    Format: trojan://<password>@<host>:<port>?<params>#<tag>
    """
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)

    def _p(key: str, default: str = "") -> str:
        return params.get(key, [default])[0]

    tag = unquote(parsed.fragment) if parsed.fragment else "trojan-node"
    host = parsed.hostname or ""
    port = parsed.port or 443
    password = unquote(parsed.username or "")

    outbound: dict[str, Any] = {
        "type": "trojan",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": _p("sni") or host,
        },
    }

    fp = _p("fp")
    if fp:
        outbound["tls"]["utls"] = {"enabled": True, "fingerprint": fp}

    transport_type = _p("type")
    if transport_type and transport_type != "tcp":
        outbound["transport"] = _build_transport(transport_type, params, host)

    return outbound


def _parse_shadowsocks(uri: str) -> dict[str, Any]:
    """Parse a Shadowsocks (ss://) URI into a sing-box outbound.

    Supports both the legacy Base64 format and the modern SIP002 format.
    """
    parsed = urlparse(uri)
    tag = unquote(parsed.fragment) if parsed.fragment else "ss-node"

    if parsed.username and parsed.hostname:
        # SIP002 format: ss://<method>:<password>@<host>:<port>#<tag>
        # OR the newer form where userinfo is base64(method:password)
        userinfo = parsed.username
        try:
            padded = userinfo + "=" * (-len(userinfo) % 4)
            decoded = base64.b64decode(padded).decode("utf-8")
            if ":" in decoded:
                method, password = decoded.split(":", 1)
            else:
                method, password = "aes-256-gcm", userinfo
        except Exception:
            # Plain userinfo = method, password separate
            method = unquote(parsed.username)
            password = unquote(parsed.password or "")

        host = parsed.hostname
        port = parsed.port or 8388
    else:
        # Legacy: ss://<base64(method:password@host:port)>#<tag>
        raw = uri[5:].split("#")[0]
        try:
            padded = raw + "=" * (-len(raw) % 4)
            decoded = base64.b64decode(padded).decode("utf-8")
        except Exception as exc:
            raise ValueError(f"Cannot decode Shadowsocks URI: {exc}") from exc

        user_part, server_part = decoded.rsplit("@", 1)
        method, password = user_part.split(":", 1)
        host, port_str = server_part.rsplit(":", 1)
        port = int(port_str)

    return {
        "type": "shadowsocks",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
    }


def _parse_hysteria(uri: str) -> dict[str, Any]:
    """Parse a Hysteria (v1) URI into a sing-box outbound.

    Format: hysteria://<host>:<port>?auth=<token>&upmbps=...&downmbps=...#<tag>
    """
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)

    def _p(key: str, default: str = "") -> str:
        return params.get(key, [default])[0]

    tag = unquote(parsed.fragment) if parsed.fragment else "hysteria-node"
    host = parsed.hostname or ""
    port = parsed.port or 443

    return {
        "type": "hysteria",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "auth_str": _p("auth") or _p("auth_str"),
        "up_mbps": int(_p("upmbps") or _p("up", "100")),
        "down_mbps": int(_p("downmbps") or _p("down", "100")),
        "tls": {
            "enabled": True,
            "server_name": _p("peer") or _p("sni") or host,
            "insecure": _p("insecure") == "1",
        },
    }


def _parse_hysteria2(uri: str) -> dict[str, Any]:
    """Parse a Hysteria2 (hy2://) URI into a sing-box outbound.

    Format: hysteria2://<password>@<host>:<port>?sni=<sni>#<tag>
    """
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)

    def _p(key: str, default: str = "") -> str:
        return params.get(key, [default])[0]

    tag = unquote(parsed.fragment) if parsed.fragment else "hysteria2-node"
    host = parsed.hostname or ""
    port = parsed.port or 443
    password = unquote(parsed.username or "")

    return {
        "type": "hysteria2",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": _p("sni") or host,
            "insecure": _p("insecure") == "1",
        },
    }


def _parse_tuic(uri: str) -> dict[str, Any]:
    """Parse a TUIC URI into a sing-box outbound.

    Format: tuic://<uuid>:<password>@<host>:<port>?<params>#<tag>
    """
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)

    def _p(key: str, default: str = "") -> str:
        return params.get(key, [default])[0]

    tag = unquote(parsed.fragment) if parsed.fragment else "tuic-node"
    uuid = parsed.username or ""
    password = parsed.password or ""
    host = parsed.hostname or ""
    port = parsed.port or 443

    outbound: dict[str, Any] = {
        "type": "tuic",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "uuid": uuid,
        "password": password,
        "congestion_control": _p("congestion_control", "bbr"),
        "tls": {
            "enabled": True,
            "server_name": _p("sni", host),
            "insecure": _p("allowInsecure", "0") in ("1", "true") or _p("insecure") == "1",
        },
    }
    alpn_str = _p("alpn")
    if alpn_str:
        outbound["tls"]["alpn"] = [a.strip() for a in alpn_str.split(",") if a.strip()]

    return outbound


def _parse_anytls(uri: str) -> dict[str, Any]:
    """Parse an AnyTLS URI into a sing-box outbound.

    Format: anytls://<password>@<host>:<port>?<params>#<tag>
    """
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)

    def _p(key: str, default: str = "") -> str:
        return params.get(key, [default])[0]

    tag = unquote(parsed.fragment) if parsed.fragment else "anytls-node"
    password = unquote(parsed.password or parsed.username or "")
    host = parsed.hostname or ""
    port = parsed.port or 443

    insecure_val = _p("insecure", _p("allowInsecure", "0")).lower()
    insecure = insecure_val in ("1", "true", "yes")

    outbound: dict[str, Any] = {
        "type": "anytls",
        "tag": _slug(tag),
        "server": host,
        "server_port": port,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": _p("sni") or _p("peer") or host,
            "insecure": insecure,
        },
    }

    fp = _p("fp")
    if fp:
        outbound["tls"]["utls"] = {"enabled": True, "fingerprint": fp}

    alpn_str = _p("alpn")
    if alpn_str:
        outbound["tls"]["alpn"] = [a.strip() for a in alpn_str.split(",") if a.strip()]

    idle_interval = _p("idle_session_check_interval")
    if idle_interval:
        outbound["idle_session_check_interval"] = idle_interval

    idle_timeout = _p("idle_session_timeout")
    if idle_timeout:
        outbound["idle_session_timeout"] = idle_timeout

    min_idle = _p("min_idle_session")
    if min_idle:
        try:
            outbound["min_idle_session"] = int(min_idle)
        except ValueError:
            pass

    return outbound


# ---------------------------------------------------------------------------
# Transport builder
# ---------------------------------------------------------------------------

def _build_transport(
    transport_type: str,
    params: dict[str, list[str]],
    host: str,
) -> dict[str, Any]:
    """Build a sing-box transport dict for the given network type."""

    def _p(key: str, default: str = "") -> str:
        return params.get(key, [default])[0]

    if transport_type == "ws":
        t: dict[str, Any] = {"type": "ws"}
        path = _p("path", "/")
        if path:
            t["path"] = path
        h = _p("host") or host
        if h:
            t["headers"] = {"Host": h}
        return t

    if transport_type in ("grpc", "gun"):
        return {
            "type": "grpc",
            "service_name": _p("serviceName") or _p("path", ""),
        }

    if transport_type == "http":
        return {
            "type": "http",
            "host": [_p("host") or host],
            "path": _p("path", "/"),
        }

    if transport_type == "quic":
        return {"type": "quic"}

    # Unknown transport — pass through as-is for forward compatibility
    logger.warning("Unknown transport type '%s'; passing raw to sing-box.", transport_type)
    return {"type": transport_type}


# ---------------------------------------------------------------------------
# Config wrapper
# ---------------------------------------------------------------------------

def _wrap_outbounds(outbounds: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap a list of outbounds into a minimal sing-box config skeleton.

    Adds:
      - A 'direct' fallback outbound
      - Route rules that forward all traffic to the first node
      - Basic DNS and logging config

    The inbounds block is intentionally omitted here — process.py injects
    the runtime-assigned socks5/http ports just before launch.
    """
    if not outbounds:
        raise ValueError("Outbounds list must not be empty.")

    primary_tag = outbounds[0].get("tag", "proxy")

    # Deduplicate tags (subscription may have duplicates)
    seen: dict[str, int] = {}
    for ob in outbounds:
        tag = ob.get("tag", "proxy")
        if tag in seen:
            seen[tag] += 1
            ob["tag"] = f"{tag}_{seen[tag]}"
        else:
            seen[tag] = 0

    return {
        "log": {
            "level": "warn",
            "timestamp": True,
        },
        "dns": {
            "servers": [
                {"tag": "remote-dns", "type": "udp", "server": "8.8.8.8"},
                {"tag": "local-dns",  "type": "local"},
            ],
        },
        "outbounds": outbounds + [
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "default_domain_resolver": "local-dns",
            "rules": [
                {"inbound": ["socks-in", "http-in"], "outbound": primary_tag},
            ],
            "final": primary_tag,
            "auto_detect_interface": True,
        },
        # inbounds injected by process.py at runtime
    }
