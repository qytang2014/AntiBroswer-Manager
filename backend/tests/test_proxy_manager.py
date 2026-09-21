"""Unit tests for Subscription and Proxy Node management (Database, Services, and REST APIs)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend import database as db
from backend.subscription_service import (
    parse_multiline_nodes,
    fetch_and_update_subscription,
)


def test_parse_multiline_nodes():
    text = """
    # Comment line
    vless://uuid-1@1.2.3.4:443?type=ws&security=tls#Node1
    vmess://eyJ2IjoiMiIsInBzIjoiTm9kZTIiLCJhZGQiOiIxLjIuMy41IiwicG9ydCI6NDQzLCJpZCI6InV1aWQtMiJ9
    ss://YWVzLTEyOC1nY206cGFzc3dvcmRAMS4yLjMuNjo4MzM4#Node3
    trojan://pass3@1.2.3.7:443#Node4
    tuic://uuid-5:pass5@1.2.3.8:8443?congestion_control=bbr#Node5
    socks5://user:pass@1.2.3.9:1080#Node6
    invalid-protocol://foo
    """
    nodes = parse_multiline_nodes(text)
    assert len(nodes) == 6

    protocols = [n["protocol"].lower() for n in nodes]
    assert "vless" in protocols
    assert "vmess" in protocols
    assert "shadowsocks" in protocols
    assert "trojan" in protocols
    assert "tuic" in protocols
    assert "socks5" in protocols

    names = [n["name"] for n in nodes]
    assert "Node1" in names
    assert "Node2" in names
    assert "Node3" in names
    assert "Node4" in names
    assert "Node5" in names
    assert "Node6" in names


def test_parse_base64_subscription():
    plain = "vless://u1@1.1.1.1:443#B64Node1\nvless://u2@2.2.2.2:443#B64Node2\n"
    b64_content = base64.b64encode(plain.encode("utf-8")).decode("utf-8")

    nodes = parse_multiline_nodes(b64_content)
    assert len(nodes) == 2
    assert nodes[0]["name"] == "B64Node1"
    assert nodes[1]["name"] == "B64Node2"


def test_subscription_crud_and_api(app_client, tmp_db):
    # 1. Create subscription via REST
    resp = app_client.post(
        "/api/proxies/subscriptions",
        json={"name": "TestSub", "url": "https://example.com/sub", "update_interval_hours": 24},
    )
    assert resp.status_code == 201
    sub_data = resp.json()
    sub_id = sub_data["id"]
    assert sub_data["name"] == "TestSub"
    assert sub_data["update_interval_hours"] == 24

    # 2. List subscriptions
    resp = app_client.get("/api/proxies/subscriptions")
    assert resp.status_code == 200
    subs = resp.json()
    assert any(s["id"] == sub_id for s in subs)

    # 3. Update subscription
    resp = app_client.put(
        f"/api/proxies/subscriptions/{sub_id}",
        json={"name": "UpdatedSub", "update_interval_hours": 72},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["name"] == "UpdatedSub"
    assert updated["update_interval_hours"] == 72

    # 4. Batch add nodes to subscription
    node_text = (
        "vless://uuid-sub-1@1.1.1.1:443#SubNode1\n"
        "trojan://pass-sub-2@2.2.2.2:443#SubNode2\n"
    )
    resp = app_client.post(
        "/api/proxies/nodes/batch",
        json={"text": node_text, "subscription_id": sub_id},
    )
    assert resp.status_code == 201
    added_nodes = resp.json()
    assert len(added_nodes) == 2

    # Verify node_count in subscription list
    resp = app_client.get("/api/proxies/subscriptions")
    subs = resp.json()
    sub_item = next(s for s in subs if s["id"] == sub_id)
    assert sub_item["node_count"] == 2

    # 5. Delete subscription (should cascade delete its nodes)
    resp = app_client.delete(f"/api/proxies/subscriptions/{sub_id}")
    assert resp.status_code == 200

    # Verify nodes are deleted
    resp = app_client.get(f"/api/proxies/nodes?subscription_id={sub_id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_proxy_nodes_api_and_testing(app_client, tmp_db):
    # 1. Add manual nodes
    manual_text = (
        "vless://u1@1.2.3.4:443#ManualNode1\n"
        "vmess://eyJ2IjoiMiIsInBzIjoiTWFudWFsTm9kZTIiLCJhZGQiOiIxLjIuMy41IiwicG9ydCI6NDQzLCJpZCI6InV1aWQtMiJ9\n"
    )
    resp = app_client.post("/api/proxies/nodes/batch", json={"text": manual_text})
    assert resp.status_code == 201
    nodes = resp.json()
    assert len(nodes) == 2
    node1_id = nodes[0]["id"]
    node2_id = nodes[1]["id"]

    # 2. Get manual nodes
    resp = app_client.get("/api/proxies/nodes?manual=true")
    assert resp.status_code == 200
    manual_nodes = resp.json()
    assert len(manual_nodes) == 2

    # 3. Test single node (mock browser_manager._test_proxy_sync)
    mock_test_result = {
        "latency_ms": 150,
        "ok": True,
        "ip": "1.2.3.4",
        "error": None,
    }
    with patch("backend.browser_manager._test_proxy_sync", return_value=mock_test_result):
        resp = app_client.post(f"/api/proxies/nodes/{node1_id}/test")
        assert resp.status_code == 200
        result = resp.json()
        assert result["ok"] is True
        assert result["latency_ms"] == 150

    # Verify DB latency updated
    node1_db = db.get_proxy_node(node1_id)
    assert node1_db["last_latency_ms"] == 150

    # 4. Batch test nodes (mock test_batch_nodes)
    mock_batch_results = [
        {"node_id": node1_id, "latency_ms": 120, "ok": True, "error": None},
        {"node_id": node2_id, "latency_ms": -1, "ok": False, "error": "Connection timed out"},
    ]
    with patch("backend.subscription_service.test_batch_nodes", return_value=mock_batch_results):
        resp = app_client.post(
            "/api/proxies/nodes/test-batch",
            json={"node_ids": [node1_id, node2_id]},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 2
        assert results[0]["latency_ms"] == 120
        assert results[1]["latency_ms"] == -1

    # 5. Delete single node
    resp = app_client.delete(f"/api/proxies/nodes/{node2_id}")
    assert resp.status_code == 200
    assert db.get_proxy_node(node2_id) is None
