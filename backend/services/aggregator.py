"""Traffic Aggregator: composes NetworkStateFrame from raw adapter data.

Responsibilities:
- Track WAN counter deltas to compute bps rates
- Aggregate firewall connections per client IP
- Enrich devices with DNS-resolved top destinations
- Enrich devices with Wi-Fi signal data
- Classify devices via DeviceClassifier
- Track device lifecycle events (connected / disconnected)
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from backend.adapters.base import BaseNetworkAdapter
from backend.models.network import (
    DeviceNode,
    DeviceStatus,
    DeviceType,
    NetworkEvent,
    NetworkStateFrame,
    SystemHealth,
    TopDestination,
    TrafficFlow,
    TransportProtocol,
    WireGuardPeer,
)
from backend.services.classifier import DeviceClassifier


@dataclass
class _DeviceState:
    """Runtime tracking state for a single device."""
    node: DeviceNode
    prev_orig_bytes: int = 0
    prev_repl_bytes: int = 0
    last_seen: float = field(default_factory=time.time)


class TrafficAggregator:
    """Polls the active adapter and assembles NetworkStateFrame snapshots.

    Maintains per-device byte counters and WAN interface counters across
    successive polls to compute instant bps rates via delta calculation.
    """

    # Devices not seen after this many seconds enter DISCONNECTING state
    DISCONNECTING_TIMEOUT_SEC: float = 10.0
    # Devices in DISCONNECTING state are removed after this many seconds
    OFFLINE_TIMEOUT_SEC: float = 30.0

    def __init__(
        self,
        adapter: BaseNetworkAdapter,
        classifier: DeviceClassifier | None = None,
    ) -> None:
        self.adapter = adapter
        self.classifier = classifier or DeviceClassifier()

        # WAN counter state: (prev_rx, prev_tx, prev_timestamp)
        self._wan_prev_rx: int = 0
        self._wan_prev_tx: int = 0
        self._wan_prev_time: float = 0.0
        self._wan_rx_bps: int = 0
        self._wan_tx_bps: int = 0

        # Per-device state keyed by MAC address
        self._devices: dict[str, _DeviceState] = {}

        # Recent events buffer (max 100 entries)
        self._events: list[NetworkEvent] = []

        self._last_poll_time: float = 0.0

    def _push_event(self, event_type: str, description: str) -> None:
        self._events.append(
            NetworkEvent(
                timestamp=time.time(),
                event_type=event_type,
                description=description,
            )
        )
        # Keep only the most recent 100 events
        if len(self._events) > 100:
            self._events = self._events[-100:]

    def _update_wan_rate(self, rx_bytes: int, tx_bytes: int) -> None:
        now = time.time()
        if self._wan_prev_time > 0:
            dt = max(0.1, now - self._wan_prev_time)
            self._wan_rx_bps = max(0, int((rx_bytes - self._wan_prev_rx) / dt)) * 8
            self._wan_tx_bps = max(0, int((tx_bytes - self._wan_prev_tx) / dt)) * 8
        self._wan_prev_rx = rx_bytes
        self._wan_prev_tx = tx_bytes
        self._wan_prev_time = now

    def _aggregate_connections(
        self,
        raw_conns: list[dict[str, Any]],
        dns_cache: dict[str, str],
    ) -> tuple[
        dict[str, int],                            # client_ip -> repl_bytes total
        dict[str, int],                            # client_ip -> orig_bytes total
        dict[str, list[dict[str, Any]]],           # client_ip -> top destination records
        list[TrafficFlow],                         # active flows list
    ]:
        """Aggregates raw firewall connection records per client IP."""
        repl_by_ip: dict[str, int] = defaultdict(int)
        orig_by_ip: dict[str, int] = defaultdict(int)
        destinations_by_ip: dict[str, dict[str, dict]] = defaultdict(dict)
        flows: list[TrafficFlow] = []

        for conn in raw_conns:
            src = conn.get("src-address", "")
            dst = conn.get("dst-address", "")
            if not src or not dst:
                continue

            client_ip = src.split(":")[0]
            dst_ip = dst.split(":")[0]
            protocol_raw = str(conn.get("protocol", "other")).lower()
            orig = int(conn.get("orig-bytes", 0) or 0)
            repl = int(conn.get("repl-bytes", 0) or 0)
            dst_port = int(conn.get("dst-port", 0) or 0)

            repl_by_ip[client_ip] += repl
            orig_by_ip[client_ip] += orig

            # Build per-destination aggregation for top destinations card
            domain = dns_cache.get(dst_ip)
            dest_key = domain or dst_ip
            if dest_key not in destinations_by_ip[client_ip]:
                destinations_by_ip[client_ip][dest_key] = {
                    "destination": dst_ip,
                    "domain": domain,
                    "protocol": protocol_raw,
                    "bytes_count": 0,
                    "connections_count": 0,
                }
            destinations_by_ip[client_ip][dest_key]["bytes_count"] += orig + repl
            destinations_by_ip[client_ip][dest_key]["connections_count"] += 1

            # Emit a TrafficFlow for the particle system
            protocol = self._map_protocol(protocol_raw)
            flows.append(
                TrafficFlow(
                    client_ip=client_ip,
                    destination_ip=dst_ip,
                    destination_domain=domain,
                    protocol=protocol,
                    dst_port=dst_port,
                    bytes_per_sec=0,  # filled in per-device below
                )
            )

        return repl_by_ip, orig_by_ip, destinations_by_ip, flows

    @staticmethod
    def _map_protocol(raw: str) -> TransportProtocol:
        if raw == "tcp":
            return TransportProtocol.TCP
        if raw == "udp":
            return TransportProtocol.UDP
        if raw in ("icmp", "icmpv6"):
            return TransportProtocol.ICMP
        return TransportProtocol.OTHER

    async def build_frame(self) -> NetworkStateFrame:
        """Fetches all data from adapter and assembles a complete NetworkStateFrame."""
        now = time.time()
        dt = max(0.1, now - self._last_poll_time) if self._last_poll_time > 0 else 1.0
        self._last_poll_time = now

        # --- Parallel fetch (sequential for simplicity; asyncio.gather in Phase 5) ---
        system_health: SystemHealth = await self.adapter.get_system_health()
        dhcp_leases: list[dict] = await self.adapter.get_dhcp_leases()
        raw_conns: list[dict] = await self.adapter.get_connections()
        wifi_regs: list[dict] = await self.adapter.get_wifi_registrations()
        dns_cache_raw: list[dict] = await self.adapter.get_dns_cache()
        wan_rx, wan_tx = await self.adapter.get_wan_counters()
        wg_peers: list[WireGuardPeer] = await self.adapter.get_wireguard_peers()

        # --- WAN rate delta ---
        self._update_wan_rate(wan_rx, wan_tx)
        system_health = system_health.model_copy(update={
            "wan_download_bps": self._wan_rx_bps,
            "wan_upload_bps": self._wan_tx_bps,
            "active_connections_count": len(raw_conns),
        })

        # --- Build DNS lookup table: IP -> domain ---
        dns_map: dict[str, str] = {}
        for entry in dns_cache_raw:
            ip = entry.get("address") or entry.get("data", "")
            name = entry.get("name", "")
            if ip and name:
                dns_map[ip] = name

        # --- Build Wi-Fi lookup: MAC (upper) -> signal/rates ---
        wifi_map: dict[str, dict] = {}
        for reg in wifi_regs:
            mac_key = str(reg.get("mac-address", "")).upper()
            if mac_key:
                wifi_map[mac_key] = reg

        # --- Aggregate connections ---
        repl_by_ip, orig_by_ip, dests_by_ip, raw_flows = self._aggregate_connections(
            raw_conns, dns_map
        )

        # --- Build IP -> MAC reverse from DHCP leases ---
        ip_to_mac: dict[str, str] = {}
        for lease in dhcp_leases:
            ip = lease.get("address", "")
            mac = str(lease.get("mac-address", "")).upper()
            if ip and mac:
                ip_to_mac[ip] = mac

        # --- Per-device rate computation ---
        # Map MAC -> total bytes from connections
        mac_repl: dict[str, int] = defaultdict(int)
        mac_orig: dict[str, int] = defaultdict(int)
        mac_dests: dict[str, dict[str, dict]] = defaultdict(dict)

        for client_ip, repl in repl_by_ip.items():
            mac = ip_to_mac.get(client_ip, client_ip)
            mac_repl[mac] += repl
        for client_ip, orig in orig_by_ip.items():
            mac = ip_to_mac.get(client_ip, client_ip)
            mac_orig[mac] += orig
        for client_ip, dests in dests_by_ip.items():
            mac = ip_to_mac.get(client_ip, client_ip)
            mac_dests[mac].update(dests)

        # --- Update device states from DHCP ---
        active_macs: set[str] = set()
        for lease in dhcp_leases:
            mac = str(lease.get("mac-address", "")).upper()
            if not mac:
                continue
            active_macs.add(mac)
            ip = lease.get("address", "")
            hostname = lease.get("host-name")
            comment = lease.get("comment")

            # Classify device
            device_type, vendor = self.classifier.classify(comment, hostname, mac)

            # Wi-Fi enrichment
            wifi_info = wifi_map.get(mac, {})
            signal_dbm: int | None = wifi_info.get("signal")
            tx_rate: str | None = wifi_info.get("tx-rate")
            rx_rate: str | None = wifi_info.get("rx-rate")

            # Traffic bytes
            curr_repl = mac_repl.get(mac, 0)
            curr_orig = mac_orig.get(mac, 0)

            # Rate calculation via delta
            if mac in self._devices:
                prev_state = self._devices[mac]
                prev_repl = prev_state.prev_repl_bytes
                prev_orig = prev_state.prev_orig_bytes
                rate_rx_bps = max(0, int((curr_repl - prev_repl) / dt)) * 8
                rate_tx_bps = max(0, int((curr_orig - prev_orig) / dt)) * 8
                was_offline = prev_state.node.status in (
                    DeviceStatus.DISCONNECTING, DeviceStatus.OFFLINE
                )
                if was_offline:
                    self._push_event("connected", f"{hostname or mac} ({ip}) connected")
            else:
                rate_rx_bps = 0
                rate_tx_bps = 0
                self._push_event("connected", f"{hostname or mac} ({ip}) connected")

            # Build top destinations list (top 5 by bytes)
            raw_dest_records = mac_dests.get(mac, {})
            sorted_dests = sorted(
                raw_dest_records.values(),
                key=lambda d: d["bytes_count"],
                reverse=True,
            )[:5]
            top_destinations = [
                TopDestination(
                    destination=d["destination"],
                    domain=d.get("domain"),
                    protocol=self._map_protocol(d["protocol"]),
                    bytes_count=d["bytes_count"],
                    connections_count=d["connections_count"],
                )
                for d in sorted_dests
            ]

            node = DeviceNode(
                id=mac,
                ip=ip,
                mac=mac,
                hostname=hostname,
                comment=comment,
                device_type=device_type,
                vendor=vendor,
                status=DeviceStatus.CONNECTED,
                wifi_signal_dbm=signal_dbm,
                wifi_tx_rate=tx_rate,
                wifi_rx_rate=rx_rate,
                rate_rx_bps=rate_rx_bps,
                rate_tx_bps=rate_tx_bps,
                total_rx_bytes=curr_repl,
                total_tx_bytes=curr_orig,
                last_seen=now,
                top_destinations=top_destinations,
            )

            self._devices[mac] = _DeviceState(
                node=node,
                prev_orig_bytes=curr_orig,
                prev_repl_bytes=curr_repl,
                last_seen=now,
            )

        # --- Transition missing devices to DISCONNECTING / OFFLINE ---
        for mac, state in list(self._devices.items()):
            if mac in active_macs:
                continue
            age = now - state.last_seen
            node = state.node
            if age < self.DISCONNECTING_TIMEOUT_SEC:
                if node.status == DeviceStatus.CONNECTED:
                    self._push_event(
                        "disconnected",
                        f"{node.hostname or mac} ({node.ip}) disconnected",
                    )
                updated = node.model_copy(update={
                    "status": DeviceStatus.DISCONNECTING,
                    "rate_rx_bps": 0,
                    "rate_tx_bps": 0,
                })
                self._devices[mac] = _DeviceState(
                    node=updated,
                    prev_orig_bytes=state.prev_orig_bytes,
                    prev_repl_bytes=state.prev_repl_bytes,
                    last_seen=state.last_seen,
                )
            elif age < self.OFFLINE_TIMEOUT_SEC:
                updated = node.model_copy(update={"status": DeviceStatus.OFFLINE})
                self._devices[mac] = _DeviceState(
                    node=updated,
                    prev_orig_bytes=state.prev_orig_bytes,
                    prev_repl_bytes=state.prev_repl_bytes,
                    last_seen=state.last_seen,
                )
            else:
                del self._devices[mac]

        # --- Compute flows with per-device bps rates ---
        updated_flows: list[TrafficFlow] = []
        seen_client_ips: set[str] = set()
        for flow in raw_flows:
            if flow.client_ip in seen_client_ips:
                continue
            seen_client_ips.add(flow.client_ip)
            mac = ip_to_mac.get(flow.client_ip, flow.client_ip)
            dev_state = self._devices.get(mac)
            rate = dev_state.node.rate_rx_bps if dev_state else 0
            updated_flows.append(flow.model_copy(update={"bytes_per_sec": rate // 8}))

        devices_list = [s.node for s in self._devices.values()]

        return NetworkStateFrame(
            timestamp=now,
            system=system_health,
            devices=devices_list,
            flows=updated_flows,
            events=list(self._events),
            wireguard_peers=wg_peers,
        )
