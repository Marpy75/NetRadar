"""Integration tests for WireGuard API endpoints via FastAPI TestClient."""

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from backend.api.wireguard import router as wireguard_router


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(wireguard_router)
    return test_app


@pytest.mark.asyncio
class TestWireGuardAPI:
    async def test_init_interface_returns_commands(self, app: FastAPI):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/wireguard/init-interface",
                json={
                    "interface_name": "wireguard1",
                    "listen_port": 13231,
                    "tunnel_subnet": "10.10.0.0/24",
                    "client_ip": "10.10.0.2/32",
                    "server_endpoint": "vpn.home.net:13231",
                    "allowed_ips": ["10.10.0.0/24", "10.20.0.0/24"],
                    "dns": "10.20.0.1",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "client_private_key" in body
        assert "client_public_key" in body
        assert "routeros_commands" in body
        assert len(body["routeros_commands"]) == 5

        cmds = body["routeros_commands"]
        # Firewall rule must include place-before=0
        fw_cmd = cmds[3]
        assert "place-before=0" in fw_cmd
        # Interface list member command
        assert "list=LAN" in cmds[2]
        # All commands tagged with netradar
        for cmd in cmds:
            assert 'comment="netradar"' in cmd

    async def test_finalize_interface_returns_config_and_qr(self, app: FastAPI):
        # Step 1: get keys
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            init_resp = await client.post(
                "/api/wireguard/init-interface",
                json={"interface_name": "wireguard1"},
            )
            init_body = init_resp.json()
            priv_key = init_body["client_private_key"]

            # Fake server public key (valid base64, 44 chars)
            fake_server_pub = "aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4yZ5aB6="

            # Step 2: finalize
            fin_resp = await client.post(
                "/api/wireguard/finalize-interface",
                json={
                    "client_private_key": priv_key,
                    "server_public_key": fake_server_pub,
                    "client_ip": "10.10.0.2/24",
                    "server_endpoint": "vpn.home.net:13231",
                    "allowed_ips": ["10.10.0.0/24"],
                    "dns": "10.20.0.1",
                },
            )

        assert fin_resp.status_code == 200
        body = fin_resp.json()
        assert "client_config_text" in body
        assert "qr_svg" in body

        conf = body["client_config_text"]
        assert "[Interface]" in conf
        assert f"PrivateKey = {priv_key}" in conf
        assert f"PublicKey = {fake_server_pub}" in conf
        assert "PersistentKeepalive = 25" in conf

        assert "<svg" in body["qr_svg"]
        assert "</svg>" in body["qr_svg"]

    async def test_add_peer_returns_full_response(self, app: FastAPI):
        fake_server_pub = "xY8kL3mN4oP5qR6sT7uV8wX9yZ0aB1cD2eF3gH4iJ="
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/wireguard/add-peer",
                json={
                    "interface_name": "wireguard1",
                    "server_public_key": fake_server_pub,
                    "client_ip": "10.10.0.5/32",
                    "server_endpoint": "vpn.home.net:13231",
                    "allowed_ips": ["0.0.0.0/0"],
                    "dns": "1.1.1.1",
                },
            )

        assert resp.status_code == 200
        body = resp.json()

        assert len(body["client_private_key"]) == 44
        assert len(body["client_public_key"]) == 44
        assert 'comment="netradar"' in body["routeros_command"]
        assert "allowed-address=10.10.0.5/32" in body["routeros_command"]
        assert "[Interface]" in body["client_config_text"]
        assert "<svg" in body["qr_svg"]

    async def test_finalize_missing_fields_returns_422(self, app: FastAPI):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/wireguard/finalize-interface",
                json={
                    "client_private_key": "",
                    "server_public_key": "",
                },
            )
        assert resp.status_code == 422

    async def test_add_peer_missing_server_key_returns_422(self, app: FastAPI):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/wireguard/add-peer",
                json={
                    "interface_name": "wireguard1",
                    "server_public_key": "",
                    "client_ip": "10.10.0.5/32",
                },
            )
        assert resp.status_code == 422
