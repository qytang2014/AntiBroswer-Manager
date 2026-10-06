"""Unit tests for system proxy detection and TCP RTT fast path."""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from backend.subscription_service import (
    _extract_server_host_port,
    _tcp_ping_rtt,
    test_node_sync as run_test_node_sync,
)
from backend.system_proxy_detector import get_system_proxy_status


def test_system_proxy_status_api(app_client: TestClient):
    """Test GET /api/system/proxy-status returns valid schema."""
    with patch(
        "backend.system_proxy_detector.get_system_proxy_status",
        return_value={
            "active": True,
            "tun_mode": True,
            "http_proxy": "127.0.0.1:7890",
            "detected_app": "Karing",
        },
    ):
        resp = app_client.get("/api/system/proxy-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["tun_mode"] is True
        assert data["http_proxy"] == "127.0.0.1:7890"
        assert data["detected_app"] == "Karing"


def test_system_proxy_detector_darwin_scutil_and_karing():
    """Test detector logic when scutil reports proxy and Karing process is running."""
    scutil_output = """<dictionary> {
  HTTPEnable : 1
  HTTPPort : 7890
  HTTPProxy : 127.0.0.1
}"""
    ps_output = "/Applications/Karing.app/Contents/MacOS/Karing\n/usr/sbin/syslogd"

    with patch("backend.system_proxy_detector._STATUS_CACHE", None), \
         patch("platform.system", return_value="Darwin"), \
         patch("subprocess.check_output") as mock_exec:

        def fake_check_output(cmd, **kwargs):
            if cmd[0] == "scutil":
                if "--nc" in cmd:
                    return '* (Connected) "Karing (system)"'
                return scutil_output
            if cmd[0] == "ps":
                return ps_output
            if cmd[0] == "route":
                return "interface: utun5"
            return ""

        mock_exec.side_effect = fake_check_output

        status = get_system_proxy_status()
        assert status["active"] is True
        assert status["tun_mode"] is True
        assert status["http_proxy"] == "127.0.0.1:7890"
        assert status["detected_app"] == "Karing"


def test_system_proxy_detector_non_darwin():
    """Test detector returns empty/inactive status on non-Darwin platforms."""
    with patch("backend.system_proxy_detector._STATUS_CACHE", None), \
         patch("platform.system", return_value="Linux"):
        status = get_system_proxy_status()
        assert status["active"] is False
        assert status["tun_mode"] is False
        assert status["detected_app"] is None
        assert status["http_proxy"] is None


def test_extract_server_host_port():
    """Verify host:port extraction across diverse node representations."""
    # 1. parsed_config JSON
    node_parsed = {
        "id": "n1",
        "parsed_config": json.dumps({"server": "proxy.example.com", "server_port": 8443}),
    }
    assert _extract_server_host_port(node_parsed) == ("proxy.example.com", 8443)

    # 2. parsed_config dict
    node_dict = {
        "id": "n2",
        "parsed_config": {"host": "1.2.3.4", "port": 1080},
    }
    assert _extract_server_host_port(node_dict) == ("1.2.3.4", 1080)

    # 3. raw_uri standard
    node_uri = {
        "id": "n3",
        "raw_uri": "vless://uuid-1@edge.server.io:443?type=tcp#Node",
    }
    assert _extract_server_host_port(node_uri) == ("edge.server.io", 443)

    # 4. raw_uri vmess base64
    import base64
    vmess_payload = base64.b64encode(json.dumps({"add": "vmess.host.net", "port": 10443}).encode()).decode()
    node_vmess = {
        "id": "n4",
        "raw_uri": f"vmess://{vmess_payload}",
    }
    assert _extract_server_host_port(node_vmess) == ("vmess.host.net", 10443)

    # 5. Invalid node
    assert _extract_server_host_port({"id": "n5", "raw_uri": ""}) is None


def test_tcp_ping_rtt():
    """Test TCP ping success, timeout, and connection failure cases."""
    # Success
    mock_sock = MagicMock()
    mock_sock.connect.return_value = None
    with patch("socket.socket", return_value=mock_sock), \
         patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]):
        ok, lat, err = _tcp_ping_rtt("127.0.0.1", 80)
        assert ok is True
        assert lat is not None and lat >= 1
        assert err is None

    # Timeout
    mock_sock_timeout = MagicMock()
    mock_sock_timeout.connect.side_effect = socket.timeout("timed out")
    with patch("socket.socket", return_value=mock_sock_timeout), \
         patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]):
        ok, lat, err = _tcp_ping_rtt("127.0.0.1", 80)
        assert ok is False
        assert lat is None
        assert "timed out" in (err or "")

    # OSError
    mock_sock_err = MagicMock()
    mock_sock_err.connect.side_effect = OSError("Connection refused")
    with patch("socket.socket", return_value=mock_sock_err), \
         patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]):
        ok, lat, err = _tcp_ping_rtt("127.0.0.1", 80)
        assert ok is False
        assert lat is None
        assert "failed" in (err or "")


def test_test_node_sync_fast_path(tmp_db):
    """Test test_node_sync uses TCP fast path and updates database."""
    node = {
        "id": "node-fast-1",
        "protocol": "VLESS",
        "raw_uri": "vless://u1@1.2.3.4:443#FastNode",
        "parsed_config": json.dumps({"server": "1.2.3.4", "server_port": 443}),
    }
    with patch("backend.subscription_service._tcp_ping_rtt", return_value=(True, 42, None)) as mock_ping, \
         patch("backend.subscription_service.update_proxy_node_latency") as mock_db_update:
        res = run_test_node_sync(node)
        assert res.ok is True
        assert res.latency_ms == 42
        mock_ping.assert_called_once_with("1.2.3.4", 443)
        mock_db_update.assert_called_once_with("node-fast-1", 42)


def test_udp_protocols_fast_icmp_ping(tmp_db):
    """Test that TUIC and Hysteria 2 UDP protocols use fast 1-RTT ICMP ping when available."""
    node = {
        "id": "node-udp-1",
        "protocol": "TUIC",
        "raw_uri": "tuic://uuid:pass@1.2.3.4:443#UdpNode",
        "parsed_config": json.dumps({"type": "tuic", "server": "1.2.3.4", "server_port": 443}),
    }
    with patch("backend.subscription_service._icmp_ping_rtt", return_value=(True, 45, None)) as mock_icmp, \
         patch("backend.singbox_runner.fast_singbox_proxy") as mock_sb, \
         patch("backend.subscription_service.update_proxy_node_latency") as mock_db_update:
        res = run_test_node_sync(node)
        assert res.ok is True
        assert res.latency_ms == 45
        mock_icmp.assert_called_once()
        mock_sb.assert_not_called()
        mock_db_update.assert_called_once_with("node-udp-1", 45)


def test_udp_protocols_fallback_to_singbox(tmp_db):
    """Test that TUIC and Hysteria 2 fall back to sing-box when raw ICMP and TCP pings fail."""
    node = {
        "id": "node-udp-2",
        "protocol": "HYSTERIA2",
        "raw_uri": "hysteria2://pass@1.2.3.4:14819#Hy2Node",
        "parsed_config": json.dumps({"type": "hysteria2", "server": "1.2.3.4", "server_port": 14819}),
    }
    with patch("backend.subscription_service._icmp_ping_rtt", return_value=(False, None, "ICMP blocked")), \
         patch("backend.subscription_service._tcp_ping_rtt", return_value=(False, None, "TCP failed")), \
         patch("backend.singbox_runner.fast_singbox_proxy") as mock_sb, \
         patch("backend.subscription_service._measure_proxy_rtt", return_value=(True, 350, None)), \
         patch("backend.subscription_service.update_proxy_node_latency") as mock_db_update:
        mock_sb.return_value.__enter__ = MagicMock(return_value="http://127.0.0.1:55555")
        mock_sb.return_value.__exit__ = MagicMock()

        res = run_test_node_sync(node)
        assert res.ok is True
        assert res.latency_ms == 350
        mock_sb.assert_called_once()
        mock_db_update.assert_called_once_with("node-udp-2", 350)


def test_loopback_proxy_bypasses_tcp_ping(tmp_db):
    """Test that loopback proxies (127.0.0.1, localhost) bypass single-machine TCP ping and run end-to-end RTT."""
    node = {
        "id": "node-loopback-1",
        "protocol": "socks5",
        "raw_uri": "socks5://127.0.0.1:1080#KaringLocal",
    }
    with patch("backend.subscription_service._tcp_ping_rtt") as mock_tcp, \
         patch("backend.subscription_service._measure_proxy_rtt", return_value=(True, 280, None)) as mock_measure, \
         patch("backend.subscription_service.update_proxy_node_latency") as mock_db_update:
        res = run_test_node_sync(node)
        assert res.ok is True
        assert res.latency_ms == 280
        # Must NOT call local TCP ping to avoid false 1ms latency
        mock_tcp.assert_not_called()
        mock_measure.assert_called_once_with("socks5://127.0.0.1:1080#KaringLocal")
        mock_db_update.assert_called_once_with("node-loopback-1", 280)


