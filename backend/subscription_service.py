"""Subscription fetching, node parsing, and background scheduler for proxy management."""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import platform
import re
import socket
import subprocess
import time
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .database import (
    batch_create_proxy_nodes,
    delete_nodes_by_subscription,
    get_proxy_node,
    get_subscription,
    list_proxy_nodes,
    list_subscriptions,
    update_proxy_node_latency,
    update_subscription,
)
from .models import BatchTestResult

logger = logging.getLogger("cloakbrowser.manager.subscription")

_SCHEDULER_INTERVAL_SECONDS = 600  # Check every 10 minutes


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_timestamp(ts_str: str | None) -> datetime.datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


_SUPPORTED_SCHEMES = {
    "vless", "vmess", "trojan", "trojan-go", "ss", "shadowsocks",
    "hysteria", "hysteria2", "hy2", "tuic", "anytls", "socks5", "socks", "http", "https",
}


def parse_multiline_nodes(
    text: str, subscription_id: str | None = None
) -> list[dict[str, Any]]:
    """Parse multiline text containing proxy URIs into proxy node dicts."""
    from backend.singbox.parser import _parse_uri

    # Try decoding base64 if text appears to be base64-encoded subscription
    raw_stripped = text.strip()
    if raw_stripped and not any(
        raw_stripped.startswith(prefix)
        for prefix in ("vless://", "vmess://", "trojan://", "ss://", "socks5://", "tuic://", "hy2://", "hysteria2://", "anytls://", "http://", "https://")
    ):
        try:
            padded = raw_stripped + "=" * ((4 - len(raw_stripped) % 4) % 4)
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            if "://" in decoded:
                text = decoded
        except Exception:
            pass

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    nodes: list[dict[str, Any]] = []

    for i, line in enumerate(lines):
        if not line or line.startswith("#"):
            continue
        try:
            parsed = urlparse(line)
            scheme = parsed.scheme.lower()
            if not scheme or scheme not in _SUPPORTED_SCHEMES:
                continue

            # Extract tag/name from fragment (#tag)
            tag = unquote(parsed.fragment) if parsed.fragment else f"{scheme}-node-{i+1}"

            # If it's a singbox protocol
            if scheme in (
                "vless", "vmess", "trojan", "trojan-go", "ss", "shadowsocks",
                "hysteria", "hysteria2", "hy2", "tuic", "anytls",
                "socks5", "socks", "http", "https",
            ):
                try:
                    outbound = _parse_uri(line)
                    parsed_config = json.dumps(outbound, ensure_ascii=False)
                    tag = outbound.get("tag", tag)
                    if scheme in ("socks5", "socks"):
                        protocol = "socks5"
                    elif scheme in ("http", "https"):
                        protocol = "http"
                    else:
                        protocol = outbound.get("type", scheme)
                except Exception as exc:
                    logger.warning("Failed to parse singbox URI '%s...': %s", line[:30], exc)
                    parsed_config = None
                    if scheme in ("socks5", "socks"):
                        protocol = "socks5"
                    elif scheme in ("http", "https"):
                        protocol = "http"
                    elif scheme in ("ss", "shadowsocks"):
                        protocol = "shadowsocks"
                    else:
                        protocol = scheme
            else:
                continue

            nodes.append({
                "subscription_id": subscription_id,
                "name": tag,
                "protocol": protocol.upper(),
                "raw_uri": line,
                "parsed_config": parsed_config,
            })
        except Exception as exc:
            logger.warning("Skipping invalid proxy line '%s...': %s", line[:30], exc)

    return nodes


def parse_single_node(line: str) -> dict[str, Any]:
    """Parse a single proxy URI line into a node dict. Raises ValueError if invalid."""
    nodes = parse_multiline_nodes(line)
    if not nodes:
        raise ValueError(f"Invalid or unsupported proxy URI: {line}")
    return nodes[0]


async def fetch_subscription_content(url: str) -> str:
    """Fetch raw subscription content with timeout and corporate proxy fallback."""
    def _fetch_sync():
        try:
            resp = httpx.get(url, timeout=httpx.Timeout(30.0), follow_redirects=True)
            resp.raise_for_status()
            return resp.text.strip()
        except Exception as exc:
            try:
                with httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=True, trust_env=False) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return resp.text.strip()
            except Exception:
                raise exc

    return await asyncio.to_thread(_fetch_sync)


async def fetch_and_update_subscription(sub_id: str) -> list[dict[str, Any]]:
    """Download subscription, parse nodes, update DB, and return nodes."""
    sub = get_subscription(sub_id)
    if not sub:
        raise ValueError(f"Subscription {sub_id} not found")

    url = sub["url"]
    logger.info("Updating subscription '%s' (%s) from %s", sub["name"], sub_id, url)

    raw = await fetch_subscription_content(url)

    # Attempt Base64 decode
    try:
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.b64decode(padded).decode("utf-8").strip()
    except Exception:
        decoded = raw

    nodes = parse_multiline_nodes(decoded, subscription_id=sub_id)
    if not nodes:
        raise ValueError(f"Subscription '{sub['name']}' returned no parseable nodes.")

    # Update DB
    delete_nodes_by_subscription(sub_id)
    created_nodes = batch_create_proxy_nodes(nodes)
    update_subscription(
        sub_id,
        last_updated_at=_now(),
        node_count=len(created_nodes),
    )
    logger.info("Subscription '%s' updated: %d nodes", sub["name"], len(created_nodes))
    return created_nodes


async def check_expired_subscriptions() -> None:
    """Check for subscriptions due for automatic update and refresh them."""
    subs = list_subscriptions()
    now = datetime.datetime.now(datetime.timezone.utc)

    for sub in subs:
        interval = sub.get("update_interval_hours") or 0
        if interval <= 0:
            continue

        last_updated = _parse_timestamp(sub.get("last_updated_at"))
        should_update = False
        if last_updated is None:
            should_update = True
        else:
            diff = (now - last_updated).total_seconds()
            if diff >= interval * 3600:
                should_update = True

        if should_update:
            try:
                await fetch_and_update_subscription(sub["id"])
            except Exception as exc:
                logger.warning("Auto-update failed for subscription '%s': %s", sub["name"], exc)


async def run_subscription_scheduler() -> None:
    """Background task running in the FastAPI lifespan."""
    logger.info("Starting proxy subscription scheduler...")
    # Initial startup check
    try:
        await check_expired_subscriptions()
    except Exception as exc:
        logger.warning("Initial subscription check failed: %s", exc)

    while True:
        try:
            await asyncio.sleep(_SCHEDULER_INTERVAL_SECONDS)
            await check_expired_subscriptions()
        except asyncio.CancelledError:
            logger.info("Subscription scheduler stopped.")
            break
        except Exception as exc:
            logger.error("Error in subscription scheduler: %s", exc)


_SPEED_TEST_URLS = [
    "http://cp.cloudflare.com/generate_204",
    "http://www.gstatic.com/generate_204",
]
_NODE_TEST_TIMEOUT = 2.5  # 2.5 seconds max per test endpoint (fast fail like Clash/Karing)


def _measure_proxy_rtt(proxy_url: str, timeout: float = _NODE_TEST_TIMEOUT) -> tuple[bool, int | None, str | None]:
    """Measure pure proxy round-trip latency (RTT) using lightweight HTTP 204 endpoints.

    Returns (ok, latency_ms, error).
    """
    last_err = None
    for url in _SPEED_TEST_URLS:
        try:
            t0 = time.monotonic()
            resp = httpx.get(
                url,
                proxy=proxy_url,
                timeout=httpx.Timeout(timeout),
                follow_redirects=True,
            )
            t1 = time.monotonic()
            if resp.status_code in (200, 204):
                rtt_ms = max(1, round((t1 - t0) * 1000))
                return True, rtt_ms, None
        except Exception as exc:
            last_err = str(exc)
            continue
    return False, None, last_err or "Connection timed out"


_TCP_PING_TIMEOUT = 3.0  # seconds
_UDP_PROTOCOLS = {"tuic", "hysteria", "hysteria2", "hy2"}


def _icmp_ping_rtt(host: str, iface: str | None = None, timeout: float = 1.5) -> tuple[bool, int | None, str | None]:
    """Measure ICMP Ping RTT to host.

    Binds to physical network interface (e.g. en0) when available,
    bypassing OS-level TUN/VPN to measure direct RTT to the server host.
    """
    system = platform.system()
    cmd: list[str] = []
    if system == "Darwin":
        cmd = ["ping", "-c", "1", "-W", str(int(timeout * 1000))]
        if iface:
            cmd.extend(["-b", iface])
        cmd.append(host)
    elif system == "Linux":
        cmd = ["ping", "-c", "1", "-W", str(int(timeout))]
        if iface:
            cmd.extend(["-I", iface])
        cmd.append(host)
    elif system == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        return False, None, "Unsupported OS for ICMP ping"

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 0.5)
        if proc.returncode == 0:
            m = re.search(r"time=([\d.]+)\s*ms", proc.stdout)
            if m:
                return True, max(1, round(float(m.group(1)))), None
        return False, None, proc.stderr or proc.stdout
    except Exception as e:
        return False, None, str(e)


def _tcp_ping_rtt(host: str, port: int, timeout: float = _TCP_PING_TIMEOUT) -> tuple[bool, int | None, str | None]:
    """Measure TCP handshake RTT to host:port without HTTP overhead or sing-box startup.

    Binds to physical network interface (e.g. en0) when available,
    bypassing OS-level TUN/VPN (e.g. Karing) to measure latency directly
    from local network to proxy node.
    """
    import struct
    from backend.system_proxy_detector import get_physical_default_interface

    physical_iface = get_physical_default_interface()
    last_err: Exception | None = None

    try:
        addrinfo = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, None, f"DNS resolution failed for {host}: {e}"

    t0 = time.monotonic()
    for af, socktype, proto, _canonname, sa in addrinfo:
        sock = socket.socket(af, socktype, proto)
        sock.settimeout(timeout)
        if physical_iface:
            try:
                if platform.system() == "Darwin":
                    idx = socket.if_nametoindex(physical_iface)
                    IP_BOUND_IF = 25
                    IPV6_BOUND_IF = 125
                    if af == socket.AF_INET:
                        sock.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, struct.pack("I", idx))
                    elif af == socket.AF_INET6:
                        sock.setsockopt(socket.IPPROTO_IPV6, IPV6_BOUND_IF, struct.pack("I", idx))
                elif platform.system() == "Linux":
                    SO_BINDTODEVICE = 25
                    sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, physical_iface.encode())
            except Exception as e:
                logger.debug("Could not bind socket to interface %s: %s", physical_iface, e)

        try:
            sock.connect(sa)
            latency_ms = max(1, round((time.monotonic() - t0) * 1000))
            sock.close()
            return True, latency_ms, None
        except (socket.timeout, OSError) as e:
            last_err = e
            sock.close()

    err_msg = f"TCP connect to {host}:{port} failed: {last_err}" if last_err else f"TCP connect to {host}:{port} failed"
    return False, None, err_msg


def _extract_server_host_port(node: dict[str, Any]) -> tuple[str, int] | None:
    """Extract (host, port) from a proxy node for TCP ping.

    Supports:
    - parsed_config JSON: {"server": "...", "server_port": ...}
    - raw_uri: parsed via urlparse for http/socks5/vless/trojan etc.
    - vmess base64 JSON in raw_uri
    """
    # 1. Try parsed_config (sing-box outbound JSON)
    parsed_config = node.get("parsed_config")
    if parsed_config:
        try:
            cfg = json.loads(parsed_config) if isinstance(parsed_config, str) else parsed_config
            host = cfg.get("server") or cfg.get("host")
            port = cfg.get("server_port") or cfg.get("port")
            if host and port:
                return str(host), int(port)
        except Exception:
            pass

    # 2. Try raw_uri
    raw_uri = (node.get("raw_uri") or "").strip()
    if raw_uri:
        if raw_uri.startswith("vmess://"):
            try:
                raw_b64 = raw_uri[len("vmess://") :]
                padded = raw_b64 + "=" * ((4 - len(raw_b64) % 4) % 4)
                data = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
                host = data.get("add") or data.get("host")
                port = data.get("port")
                if host and port:
                    return str(host), int(port)
            except Exception:
                pass

        try:
            p = urlparse(raw_uri)
            if p.hostname and p.port:
                return p.hostname, p.port
        except Exception:
            pass

    return None


def test_node_sync(node: dict[str, Any]) -> BatchTestResult:
    """Test a single proxy node synchronously and record pure latency in DB.

    Transport RTT fast path:
      - For TCP protocols: TCP handshake directly to host:port. If fails, try ICMP ping.
      - For UDP protocols (TUIC, Hysteria 2): ICMP ping directly to host (fast 1-RTT ping).
        If ICMP blocked, try TCP ping to node port (if dual-stack) or port 443.
    Fallback:
      - sing-box HTTP RTT if raw transport pings fail or host:port cannot be extracted.
    """
    nid = node["id"]
    protocol = (node.get("protocol") or "").lower()
    raw_uri = (node.get("raw_uri") or "").strip()
    is_udp_protocol = protocol in _UDP_PROTOCOLS or any(
        raw_uri.lower().startswith(p) for p in ("hysteria2://", "tuic://", "hy2://", "hysteria://")
    )

    from backend.system_proxy_detector import get_physical_default_interface
    physical_iface = get_physical_default_interface()

    addr = _extract_server_host_port(node)
    if addr:
        host, port = addr
        ok, lat, err = False, None, None

        if is_udp_protocol:
            # 1. ICMP ping directly to host (matches Karing/Clash UDP latency)
            ok, lat, err = _icmp_ping_rtt(host, iface=physical_iface)
            # 2. If ICMP is blocked, try TCP ping on node port or 443
            if not ok:
                ok, lat, err = _tcp_ping_rtt(host, port)
            if not ok and port != 443:
                ok, lat, err = _tcp_ping_rtt(host, 443)
        else:
            # 1. TCP ping directly to host:port
            ok, lat, err = _tcp_ping_rtt(host, port)
            # 2. If TCP ping fails (e.g. firewall SYN drop), try ICMP ping
            if not ok:
                ok, lat, err = _icmp_ping_rtt(host, iface=physical_iface)

        if ok and lat is not None:
            update_proxy_node_latency(nid, lat)
            return BatchTestResult(node_id=nid, latency_ms=lat, ok=True)

    # Fallback / UDP path: HTTP RTT or sing-box
    parsed_config = node.get("parsed_config")

    try:
        if protocol in ("vless", "vmess", "trojan", "ss", "shadowsocks", "hysteria", "hysteria2", "hy2", "tuic", "anytls") or is_udp_protocol:
            from backend.singbox_runner import fast_singbox_proxy

            if parsed_config:
                try:
                    cfg = json.loads(parsed_config) if isinstance(parsed_config, str) else parsed_config
                    proxy_payload = {"type": "singbox", "config": {"outbounds": [cfg]}}
                except Exception:
                    proxy_payload = {"type": "singbox", "config": raw_uri}
            else:
                proxy_payload = {"type": "singbox", "config": raw_uri}

            with fast_singbox_proxy(proxy_payload) as target_proxy_url:
                ok, lat, err = _measure_proxy_rtt(target_proxy_url)
        else:
            ok, lat, err = _measure_proxy_rtt(raw_uri)
    except Exception as exc:
        ok, lat, err = False, None, str(exc)

    if ok and lat is not None:
        update_proxy_node_latency(nid, lat)
        return BatchTestResult(node_id=nid, latency_ms=lat, ok=True)
    else:
        update_proxy_node_latency(nid, -1)
        return BatchTestResult(node_id=nid, latency_ms=-1, ok=False, error=err or "Connection failed")



async def test_batch_nodes(node_ids: list[str]) -> list[BatchTestResult]:
    """Test a list of nodes concurrently with a semaphore limit."""
    sem = asyncio.Semaphore(5)

    async def _test_one(nid: str) -> BatchTestResult:
        node = get_proxy_node(nid)
        if not node:
            return BatchTestResult(node_id=nid, ok=False, error="Node not found")
        async with sem:
            return await asyncio.to_thread(test_node_sync, node)

    tasks = [_test_one(nid) for nid in node_ids]
    return await asyncio.gather(*tasks)
