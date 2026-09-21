"""Subscription fetching, node parsing, and background scheduler for proxy management."""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
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
    from cloakbrowser.singbox.parser import _parse_uri

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
            ):
                try:
                    outbound = _parse_uri(line)
                    parsed_config = json.dumps(outbound, ensure_ascii=False)
                    tag = outbound.get("tag", tag)
                    protocol = outbound.get("type", scheme)
                except Exception as exc:
                    logger.warning("Failed to parse singbox URI '%s...': %s", line[:30], exc)
                    parsed_config = None
                    protocol = "shadowsocks" if scheme in ("ss", "shadowsocks") else scheme
            elif scheme in ("socks5", "socks", "http", "https"):
                protocol = "socks5" if "socks" in scheme else "http"
                parsed_config = None
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
    "http://connectivitycheck.gstatic.com/generate_204",
]
_NODE_TEST_TIMEOUT = 3.0  # 3 seconds max per test endpoint (fast fail like Clash/Karing)


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


def test_node_sync(node: dict[str, Any]) -> BatchTestResult:
    """Test a single proxy node synchronously and record pure latency in DB."""
    nid = node["id"]
    protocol = (node.get("protocol") or "").lower()
    raw_uri = node.get("raw_uri") or ""
    parsed_config = node.get("parsed_config")

    proc = None
    try:
        if protocol in ("vless", "vmess", "trojan", "ss", "shadowsocks", "hysteria", "hysteria2", "hy2", "tuic", "anytls"):
            from cloakbrowser.singbox.manager import handle_singbox_proxy
            if parsed_config:
                try:
                    cfg = json.loads(parsed_config)
                    proxy_payload = {"type": "singbox", "config": {"outbounds": [cfg]}}
                except Exception:
                    proxy_payload = {"type": "singbox", "config": raw_uri}
            else:
                proxy_payload = {"type": "singbox", "config": raw_uri}

            proc, socks5_url = handle_singbox_proxy(proxy_payload)
            target_proxy_url = (
                f"http://127.0.0.1:{proc.http_port}"
                if proc and getattr(proc, "http_port", None)
                else socks5_url
            )
        else:
            target_proxy_url = raw_uri

        ok, lat, err = _measure_proxy_rtt(target_proxy_url)
    except Exception as exc:
        ok, lat, err = False, None, str(exc)
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.proc.kill()
                except Exception:
                    pass

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
