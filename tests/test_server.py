"""Integration tests for the FastAPI server (Phase 5)."""

import asyncio
import json
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from backend.adapters.simulator import SimulatorAdapter
from backend.main import create_app, ConnectionManager


@pytest.fixture
def sim_adapter():
    return SimulatorAdapter(seed=55)


@pytest.fixture
def app(sim_adapter):
    return create_app(sim_adapter)


@pytest.mark.asyncio
class TestServerRoutes:
    async def test_wireguard_add_peer_via_app(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/wireguard/add-peer",
                json={
                    "interface_name": "wireguard1",
                    "server_public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                    "client_ip": "10.10.0.3/32",
                    "server_endpoint": "vpn.test.home:13231",
                    "allowed_ips": ["10.10.0.0/24"],
                    "dns": "10.20.0.1",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "client_private_key" in body
        assert "routeros_command" in body
        assert 'comment="netradar"' in body["routeros_command"]

    async def test_wireguard_init_via_app(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/wireguard/init-interface",
                json={"interface_name": "wireguard1", "listen_port": 13231},
            )
        assert resp.status_code == 200
        cmds = resp.json()["routeros_commands"]
        assert any("place-before=0" in c for c in cmds)
        assert any("list=LAN" in c for c in cmds)


class TestConnectionManager:
    def test_client_count(self):
        m = ConnectionManager()
        assert m.client_count == 0

    def test_disconnect_nonexistent_is_safe(self):
        from unittest.mock import MagicMock
        m = ConnectionManager()
        ws = MagicMock()
        m.disconnect(ws)  # Should not raise
        assert m.client_count == 0


class TestWebSocketConnection:
    def test_websocket_accepts_connection(self, app):
        """Verifies the WebSocket endpoint accepts connections and the app starts."""
        with TestClient(app) as client:
            with client.websocket_connect("/ws/network") as ws:
                assert ws is not None
