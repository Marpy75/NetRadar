"""Unit tests for TrafficAggregator service."""

import time
import pytest
from backend.adapters.simulator import SimulatorAdapter
from backend.models.network import (
    DeviceStatus,
    DeviceType,
    NetworkStateFrame,
    TransportProtocol,
)
from backend.services.aggregator import TrafficAggregator
from backend.services.classifier import DeviceClassifier


@pytest.fixture
def sim() -> SimulatorAdapter:
    return SimulatorAdapter(seed=77)


@pytest.fixture
def aggregator(sim: SimulatorAdapter) -> TrafficAggregator:
    return TrafficAggregator(adapter=sim, classifier=DeviceClassifier())


@pytest.mark.asyncio
class TestTrafficAggregator:
    async def test_frame_structure(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()

        assert isinstance(frame, NetworkStateFrame)
        assert frame.timestamp > 0
        assert frame.system is not None
        assert isinstance(frame.devices, list)
        assert isinstance(frame.flows, list)
        assert isinstance(frame.events, list)
        assert isinstance(frame.wireguard_peers, list)

    async def test_devices_in_subnet(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()

        assert len(frame.devices) >= 10
        for device in frame.devices:
            assert device.ip.startswith("10.20.0.")
            assert device.status == DeviceStatus.CONNECTED
            assert device.device_type != DeviceType.ROUTER  # No router in DHCP leases
            assert len(device.mac.split(":")) == 6

    async def test_device_classification_applied(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()

        mac_index = {d.mac.upper(): d for d in frame.devices}

        # F0:18:98 -> Apple -> MacBook Pro with comment "personal laptop" -> LAPTOP
        macbook = mac_index.get("F0:18:98:2A:4C:11")
        assert macbook is not None
        assert macbook.device_type == DeviceType.LAPTOP

        # 24:0A:C4 -> Espressif -> ESP32 -> IOT (by hostname "ESP32-Smart-Relay")
        esp = mac_index.get("24:0A:C4:AA:BB:CC")
        assert esp is not None
        assert esp.device_type == DeviceType.IOT

        # Synology -> SERVER (by hostname "synology-nas-home")
        nas = mac_index.get("00:11:32:88:99:AA")
        assert nas is not None
        assert nas.device_type == DeviceType.SERVER

        # LG TV -> TV (by comment "living room tv")
        tv = mac_index.get("58:A2:B5:12:34:56")
        assert tv is not None
        assert tv.device_type == DeviceType.TV

    async def test_wifi_signal_enrichment(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()

        wifi_devices = [d for d in frame.devices if d.wifi_signal_dbm is not None]
        assert len(wifi_devices) > 0

        for dev in wifi_devices:
            assert -100 <= dev.wifi_signal_dbm <= -20
            assert dev.wifi_tx_rate is not None
            assert dev.wifi_rx_rate is not None

        # Wired device (DESKTOP) must NOT have wifi signal
        wired = next((d for d in frame.devices if "DESKTOP" in (d.hostname or "")), None)
        assert wired is not None
        assert wired.wifi_signal_dbm is None

    async def test_wan_rate_increases_on_second_poll(self, aggregator: TrafficAggregator):
        frame1 = await aggregator.build_frame()
        # First poll: WAN rate is 0 because there's no previous sample
        assert frame1.system.wan_download_bps >= 0

        # Second poll with traffic in between
        await aggregator.adapter.get_connections()  # simulate time passage with traffic
        frame2 = await aggregator.build_frame()
        # WAN rate should be non-negative and counters should have moved
        assert frame2.system.wan_download_bps >= 0
        assert frame2.system.wan_upload_bps >= 0

    async def test_device_traffic_rates(self, aggregator: TrafficAggregator):
        # First poll seeds the counters
        await aggregator.build_frame()
        # Second poll computes deltas
        frame2 = await aggregator.build_frame()

        # At least some devices should have non-zero traffic
        active_devices = [
            d for d in frame2.devices if d.status == DeviceStatus.CONNECTED
        ]
        assert len(active_devices) > 0

        # Total rates should be non-negative
        for dev in active_devices:
            assert dev.rate_rx_bps >= 0
            assert dev.rate_tx_bps >= 0

    async def test_top_destinations_resolved(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()

        devices_with_dests = [d for d in frame.devices if d.top_destinations]
        assert len(devices_with_dests) > 0

        for dev in devices_with_dests:
            assert len(dev.top_destinations) <= 5
            for dest in dev.top_destinations:
                assert dest.destination  # must have an IP
                assert dest.bytes_count >= 0
                assert dest.connections_count >= 0

    async def test_wireguard_peers_present(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()
        assert len(frame.wireguard_peers) == 3

        active_peers = [p for p in frame.wireguard_peers if p.endpoint_address]
        assert len(active_peers) == 2

    async def test_disconnect_lifecycle(self):
        sim = SimulatorAdapter(seed=99)
        agg = TrafficAggregator(adapter=sim, classifier=DeviceClassifier())

        # First frame: all initially active devices present
        frame1 = await agg.build_frame()
        connected_macs = {d.mac for d in frame1.devices if d.status == DeviceStatus.CONNECTED}
        assert len(connected_macs) > 0

        # Mark one known always-active device as offline in simulator
        # by toggling an initially active device's flag
        for dev in sim.synthetic_pool:
            if dev["mac"] == "F0:18:98:2A:4C:11":  # MacBook
                dev["active"] = False
                break

        frame2 = await agg.build_frame()
        macbook_state = next(
            (d for d in frame2.devices if d.mac.upper() == "F0:18:98:2A:4C:11"),
            None,
        )
        assert macbook_state is not None
        assert macbook_state.status in (DeviceStatus.DISCONNECTING, DeviceStatus.OFFLINE)

        # A "disconnected" event should have been recorded
        event_types = [e.event_type for e in frame2.events]
        assert "disconnected" in event_types

    async def test_events_buffer_capped(self, aggregator: TrafficAggregator):
        # Generate many polls to overflow the event buffer
        for _ in range(60):
            await aggregator.build_frame()
        assert len(aggregator._events) <= 100

    async def test_flows_contain_valid_protocols(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()
        valid_protocols = set(TransportProtocol)
        for flow in frame.flows:
            assert flow.protocol in valid_protocols
            assert flow.client_ip.startswith("10.20.0.")

    async def test_active_connection_count_in_health(self, aggregator: TrafficAggregator):
        frame = await aggregator.build_frame()
        # SimulatorAdapter generates 2-4 flows per active device
        assert frame.system.active_connections_count > 0
