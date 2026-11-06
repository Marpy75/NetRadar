"""Unit tests for RouterOSRestAdapter using purely mocked HTTP transports."""

import json
from pathlib import Path
import httpx
import pytest
from backend.adapters.adaptive import AdaptivePollingController
from backend.adapters.routeros import RouterOSConfig, RouterOSRestAdapter
from backend.models.network import SystemHealth, WireGuardPeer


@pytest.fixture
def dummy_ca_file(tmp_path: Path) -> Path:
    ca_file = tmp_path / "router_ca.crt"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\nDUMMY\n-----END CERTIFICATE-----")
    return ca_file


@pytest.fixture
def router_config(dummy_ca_file: Path) -> RouterOSConfig:
    return RouterOSConfig(
        host="192.168.88.1",
        port=443,
        username="netradar_reader",
        password="dummy_password",
        ca_path=str(dummy_ca_file),
        wan_interface="ether1",
    )


class TestAdaptivePollingController:
    def test_threshold_and_hysteresis(self):
        controller = AdaptivePollingController(
            base_interval_sec=2.0,
            high_load_interval_sec=5.0,
            high_threshold=5000,
            recovery_threshold=4000,
        )
        assert controller.current_interval == 2.0
        assert controller.is_high_load is False

        # Moderate load
        assert controller.update(3500) == 2.0
        assert controller.is_high_load is False

        # Exceed high threshold
        assert controller.update(5001) == 5.0
        assert controller.is_high_load is True

        # Hysteresis check: intermediate count between 4000 and 5000 must maintain high load
        assert controller.update(4500) == 5.0
        assert controller.is_high_load is True

        # Drop below recovery threshold
        assert controller.update(3999) == 2.0
        assert controller.is_high_load is False


@pytest.mark.asyncio
class TestRouterOSRestAdapter:
    async def test_ca_path_validation_failure(self):
        # Must fail when CA path does not exist
        cfg = RouterOSConfig(
            host="192.168.88.1",
            username="admin",
            password="pwd",
            ca_path="C:/non_existent_ca_path_file.crt",
        )
        with pytest.raises(ValueError, match="CA certificate path is invalid"):
            RouterOSRestAdapter(cfg)

    async def test_load_from_toml(self, tmp_path: Path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            'host = "10.0.0.1"\n'
            'port = 8443\n'
            'username = "admin"\n'
            'password = "secret"\n'
            'ca_path = "certs/ca.pem"\n'
            'wan_interface = "sfp-sfpplus1"\n',
            encoding="utf-8"
        )
        loaded = RouterOSConfig.from_file(toml_file)
        assert loaded.host == "10.0.0.1"
        assert loaded.port == 8443
        assert loaded.username == "admin"
        assert loaded.ca_path == "certs/ca.pem"
        assert loaded.wan_interface == "sfp-sfpplus1"

    async def test_get_system_health(self, router_config: RouterOSConfig):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/system/resource":
                return httpx.Response(
                    200,
                    json=[{
                        "cpu-load": "18",
                        "free-memory": "250000000",
                        "total-memory": "500000000",
                        "uptime": "1d2h30m10s",
                        "board-name": "RB5009UG+S+IN",
                        "version": "7.25",
                    }],
                )
            if request.url.path == "/rest/system/health":
                return httpx.Response(
                    200,
                    json=[
                        {"name": "board-temperature1", "value": "46"},
                        {"name": "cpu-temperature", "value": "51.5"},
                    ],
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            health = await adapter.get_system_health()

            assert isinstance(health, SystemHealth)
            assert health.cpu_load_percent == 18
            assert health.free_memory_bytes == 250000000
            assert health.total_memory_bytes == 500000000
            assert health.temperature_celsius == 46.0 or health.temperature_celsius == 51.5
            assert health.uptime_seconds == 86400 + 2 * 3600 + 30 * 60 + 10
            assert health.board_name == "RB5009UG+S+IN"
            assert health.routeros_version == "7.25"

    async def test_get_dhcp_leases(self, router_config: RouterOSConfig):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/rest/ip/dhcp-server/lease"
            assert request.url.params.get(".proplist") is not None
            return httpx.Response(
                200,
                json=[
                    {
                        "address": "10.20.0.10",
                        "mac-address": "F0:18:98:2A:4C:11",
                        "host-name": "MacBook-Pro",
                        "comment": "laptop",
                        "status": "bound",
                        "active-address": "10.20.0.10",
                    }
                ],
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            leases = await adapter.get_dhcp_leases()
            assert len(leases) == 1
            assert leases[0]["address"] == "10.20.0.10"
            assert leases[0]["comment"] == "laptop"

    async def test_get_connections_adaptive_trigger(self, router_config: RouterOSConfig):
        large_conn_list = [{"src-address": "10.20.0.5:1234", "orig-bytes": "100"}] * 5200

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/rest/ip/firewall/connection"
            return httpx.Response(200, json=large_conn_list)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            assert adapter.adaptive_controller.current_interval == 2.0
            conns = await adapter.get_connections()
            assert len(conns) == 5200
            assert adapter.adaptive_controller.current_interval == 5.0

    async def test_get_wifi_registrations_modern(self, router_config: RouterOSConfig):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/interface/wifi/registration-table":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "interface": "wifi1",
                            "mac-address": "28:CF:DA:3B:55:02",
                            "signal": -52,
                            "tx-rate": "433Mbps",
                            "rx-rate": "300Mbps",
                        }
                    ],
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            regs = await adapter.get_wifi_registrations()
            assert len(regs) == 1
            assert regs[0]["signal"] == -52
            assert regs[0]["signal-strength"] == "-52dBm"

    async def test_get_wifi_registrations_legacy_fallback(self, router_config: RouterOSConfig):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/interface/wifi/registration-table":
                return httpx.Response(404)
            if request.url.path == "/rest/interface/wireless/registration-table":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "interface": "wlan1",
                            "mac-address": "34:23:87:66:10:99",
                            "signal-strength": "-68dBm@ht40",
                            "tx-rate": "150Mbps",
                            "rx-rate": "130Mbps",
                        }
                    ],
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            regs = await adapter.get_wifi_registrations()
            assert len(regs) == 1
            assert regs[0]["signal"] == -68
            assert regs[0]["signal-strength"] == "-68dBm@ht40"

    async def test_get_dns_cache(self, router_config: RouterOSConfig):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/ip/dns/cache":
                return httpx.Response(
                    200,
                    json=[{"name": "telegram.org", "address": "149.154.167.99", "data": "149.154.167.99"}],
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            cache = await adapter.get_dns_cache()
            assert len(cache) == 1
            assert cache[0]["name"] == "telegram.org"

    async def test_get_wan_counters(self, router_config: RouterOSConfig):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/interface":
                return httpx.Response(
                    200,
                    json=[
                        {"name": "ether1", "rx-byte": "12345678", "tx-byte": "87654321", "running": "true"},
                        {"name": "ether2", "rx-byte": "100", "tx-byte": "200", "running": "true"},
                    ],
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            rx, tx = await adapter.get_wan_counters()
            assert rx == 12345678
            assert tx == 87654321

    async def test_get_wireguard_peers(self, router_config: RouterOSConfig):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/interface/wireguard/peers":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "interface": "wireguard1",
                            "public-key": "fake_peer_pubkey_1234567890=",
                            "endpoint-address": "198.51.100.1:41234",
                            "last-handshake": "1m15s",
                            "rx": "500000",
                            "tx": "120000",
                            "comment": "phone-remote",
                        }
                    ],
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://192.168.88.1/rest") as client:
            adapter = RouterOSRestAdapter(router_config, client=client)
            peers = await adapter.get_wireguard_peers()
            assert len(peers) == 1
            assert isinstance(peers[0], WireGuardPeer)
            assert peers[0].comment == "phone-remote"
            assert peers[0].rx_bytes == 500000
            assert peers[0].tx_bytes == 120000
