import socket
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from moviebox_app.app import create_app
from moviebox_app.launcher_network import network_addresses


@pytest.mark.parametrize("route_available", [True, False])
def test_network_discovery_deduplicates_addresses_and_skips_loopback(monkeypatch, route_available):
    probe = MagicMock()
    probe.getsockname.return_value = ("192.168.1.42", 12345)
    if not route_available:
        probe.connect.side_effect = OSError("No default route")
    factory = MagicMock()
    factory.return_value.__enter__.return_value = probe
    monkeypatch.setattr(socket, "socket", factory)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))
            for address in ["127.0.0.1", "0.0.0.0", "169.254.1.1", "192.168.1.42", "192.168.1.42"]
        ],
    )
    assert network_addresses() == ["192.168.1.42"]


def test_network_host_can_load_ui_and_use_same_origin_api(settings):
    settings.allowed_hosts.append("192.168.1.42")
    with TestClient(create_app(settings), base_url="http://192.168.1.42:8765") as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        response = client.post(
            "/api/downloads",
            headers={"Origin": "http://192.168.1.42:8765"},
            json={"url": "invalid"},
        )
        assert response.status_code == 422
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
        assert (
            client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 403
        )
