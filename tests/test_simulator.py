"""Unit tests for SimulatorAdapter."""

import pytest
from backend.adapters.simulator import SimulatorAdapter
from backend.models.network import SystemHealth, WireGuardPeer


@pytest.fixture
def sim() -> SimulatorAdapter:
    return SimulatorAdapter(seed=123)


@pytest.mark.asyncio
class TestSimulatorAdapter:
    async def test_get_system_health(self, sim: SimulatorAdapter):
        health = await sim.get_system_health()
        assert isinstance(health, SystemHealth)
        assert 0 <= health.cpu_load_percent <= 100
        assert health.temperature_celsius is not None
        assert 35.0 <= health.temperature_celsius <= 65.0
        assert health.uptime_seconds > 0
        assert health.board_name == "hAP ax3"
        assert health.routeros_version == "7.25"
        assert health.total_memory_bytes == 512 * 1024 * 1024
        assert health.free_memory_bytes > 0
        assert health.wan_download_bps >= 0
        assert health.wan_upload_bps >= 0

    async def test_get_dhcp_leases_subnet(self, sim: SimulatorAdapter):
        leases = await sim.get_dhcp_leases()
        assert len(leases) >= 10
        assert len(leases) <= 15

        for lease in leases:
            ip = lease["address"]
            mac = lease["mac-address"]
            # All devices must belong to 10.20.0.0/24 subnet
            assert ip.startswith("10.20.0.")
            assert len(mac.split(":")) == 6
            assert lease["status"] == "bound"

    async def test_get_wifi_registrations_dual_package_support(self, sim: SimulatorAdapter):
        regs = await sim.get_wifi_registrations()
        assert len(regs) > 0

        for reg in regs:
            # Modern wifi package field 'signal'
            assert "signal" in reg
            assert isinstance(reg["signal"], int)
            assert -95 <= reg["signal"] <= -30

            # Legacy wireless package field 'signal-strength'
            assert "signal-strength" in reg
            assert "dBm" in reg["signal-strength"]

            assert "mac-address" in reg
            assert "tx-rate" in reg
            assert "rx-rate" in reg

    async def test_get_dns_cache(self, sim: SimulatorAdapter):
        dns_cache = await sim.get_dns_cache()
        assert len(dns_cache) >= 5

        domains = [entry["name"] for entry in dns_cache]
        assert "youtube.com" in domains
        assert "github.com" in domains
        assert "cloudflare.com" in domains

        for entry in dns_cache:
            assert "address" in entry
            assert entry["type"] == "A"

    async def test_get_connections(self, sim: SimulatorAdapter):
        conns = await sim.get_connections()
        assert len(conns) > 0

        for conn in conns:
            assert "src-address" in conn
            assert conn["src-address"].startswith("10.20.0.")
            assert "dst-address" in conn
            assert "protocol" in conn
            assert conn["protocol"] in ["tcp", "udp"]
            assert "orig-bytes" in conn
            assert int(conn["orig-bytes"]) >= 0
            assert "repl-bytes" in conn
            assert int(conn["repl-bytes"]) >= 0

    async def test_get_wan_counters_monotonic(self, sim: SimulatorAdapter):
        rx1, tx1 = await sim.get_wan_counters()
        # Trigger connection generation to simulate traffic activity
        await sim.get_connections()
        rx2, tx2 = await sim.get_wan_counters()

        assert rx2 >= rx1
        assert tx2 >= tx1

    async def test_get_wireguard_peers(self, sim: SimulatorAdapter):
        peers = await sim.get_wireguard_peers()
        assert len(peers) == 3

        for peer in peers:
            assert isinstance(peer, WireGuardPeer)
            assert peer.interface == "wireguard1"
            assert len(peer.public_key) > 20

        peer_comments = [p.comment for p in peers]
        assert "phone-remote" in peer_comments
        assert "laptop-travel" in peer_comments
        assert "backup-offsite" in peer_comments
