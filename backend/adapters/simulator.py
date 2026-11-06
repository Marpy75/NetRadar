"""Realistic simulator adapter for MikroTik RouterOS 7.25 network state."""

import math
import random
import time
from typing import Any
from backend.adapters.base import BaseNetworkAdapter
from backend.models.network import SystemHealth, WireGuardPeer


class SimulatorAdapter(BaseNetworkAdapter):
    """Generates synthetic network data matching RouterOS REST API schemas.

    Operates in the 10.20.0.0/24 subnet with 10-15 virtual devices, simulating
    DHCP leases, connection tracking flows, Wi-Fi registrations, DNS cache,
    WAN interface traffic counters, and WireGuard tunnels.
    """

    def __init__(self, seed: int | None = 42) -> None:
        if seed is not None:
            random.seed(seed)
        self.start_time = time.time()
        self.last_tick_time = self.start_time
        self.step_counter = 0

        # WAN cumulative counters
        self.wan_rx_bytes = 1024 * 1024 * 500  # 500 MB base
        self.wan_tx_bytes = 1024 * 1024 * 120  # 120 MB base

        # Predefined synthetic devices (10.20.0.0/24)
        self.synthetic_pool: list[dict[str, Any]] = [
            {
                "ip": "10.20.0.10",
                "mac": "F0:18:98:2A:4C:11",  # Apple OUI
                "host-name": "MacBook-Pro-Alex",
                "comment": "personal laptop",
                "is_wifi": True,
                "base_rate": 850000,
                "active": True,
            },
            {
                "ip": "10.20.0.15",
                "mac": "28:CF:DA:3B:55:02",  # Apple OUI
                "host-name": "iPhone-15-Pro",
                "comment": None,
                "is_wifi": True,
                "base_rate": 220000,
                "active": True,
            },
            {
                "ip": "10.20.0.22",
                "mac": "34:23:87:66:10:99",  # Samsung OUI
                "host-name": "Galaxy-S24",
                "comment": "mobile",
                "is_wifi": True,
                "base_rate": 180000,
                "active": True,
            },
            {
                "ip": "10.20.0.25",
                "mac": "DA:A1:19:44:81:22",  # Randomized MAC (0xDA & 0x02 != 0)
                "host-name": "Android-Guest-1",
                "comment": None,
                "is_wifi": True,
                "base_rate": 95000,
                "active": True,
            },
            {
                "ip": "10.20.0.30",
                "mac": "00:1E:4F:91:22:33",  # Dell OUI
                "host-name": "DESKTOP-WS01",
                "comment": "main workstation",
                "is_wifi": False,
                "base_rate": 1200000,
                "active": True,
            },
            {
                "ip": "10.20.0.40",
                "mac": "58:A2:B5:12:34:56",  # LG OUI
                "host-name": "LG-webOSTV-OLED",
                "comment": "living room tv",
                "is_wifi": True,
                "base_rate": 1500000,
                "active": True,
            },
            {
                "ip": "10.20.0.50",
                "mac": "00:11:32:88:99:AA",  # Synology OUI
                "host-name": "synology-nas-home",
                "comment": "storage server",
                "is_wifi": False,
                "base_rate": 650000,
                "active": True,
            },
            {
                "ip": "10.20.0.60",
                "mac": "3C:4A:92:01:23:45",  # HP OUI
                "host-name": "HP-LaserJet-M404",
                "comment": "office printer",
                "is_wifi": True,
                "base_rate": 5000,
                "active": True,
            },
            {
                "ip": "10.20.0.70",
                "mac": "24:0A:C4:AA:BB:CC",  # Espressif OUI
                "host-name": "ESP32-Smart-Relay",
                "comment": "kitchen lights",
                "is_wifi": True,
                "base_rate": 1200,
                "active": True,
            },
            {
                "ip": "10.20.0.71",
                "mac": "30:AE:A4:11:22:33",  # Espressif OUI
                "host-name": "tasmota-plug-living",
                "comment": "iot power plug",
                "is_wifi": True,
                "base_rate": 800,
                "active": True,
            },
            {
                "ip": "10.20.0.80",
                "mac": "B8:27:EB:CC:DD:EE",  # Raspberry Pi OUI
                "host-name": "pi-hole-dns",
                "comment": "dns filter server",
                "is_wifi": False,
                "base_rate": 45000,
                "active": True,
            },
            {
                "ip": "10.20.0.85",
                "mac": "78:28:CA:FE:ED:01",  # Sonos OUI
                "host-name": "Sonos-LivingRoom",
                "comment": "audio streamer",
                "is_wifi": True,
                "base_rate": 250000,
                "active": True,
            },
            {
                "ip": "10.20.0.90",
                "mac": "90:72:40:11:22:99",  # Apple OUI
                "host-name": "iPad-Air-M2",
                "comment": None,
                "is_wifi": True,
                "base_rate": 140000,
                "active": False,  # Initially offline, will toggle
            },
            {
                "ip": "10.20.0.95",
                "mac": "02:BF:33:44:55:66",  # Randomized MAC
                "host-name": "Guest-Device-Mobile",
                "comment": None,
                "is_wifi": True,
                "base_rate": 60000,
                "active": False,  # Initially offline
            },
        ]

        # DNS mapping table
        self.dns_records: dict[str, str] = {
            "142.250.74.206": "youtube.com",
            "140.82.121.4": "github.com",
            "104.16.132.229": "cloudflare.com",
            "149.154.167.99": "telegram.org",
            "151.101.1.140": "reddit.com",
            "52.84.150.22": "netflix.com",
            "13.107.42.14": "microsoft.com",
            "1.1.1.1": "one.one.one.one",
            "8.8.8.8": "dns.google",
        }

        # Simulated WireGuard peers
        self.wg_peers: list[dict[str, Any]] = [
            {
                "interface": "wireguard1",
                "public-key": "vP2qO5Tf6zXjL4mK9wYb1rE8dC7vN0aQ3sZ5xW7uU9I=",
                "endpoint-address": "198.51.100.12:41234",
                "last-handshake": "42s",
                "rx": 15420000,
                "tx": 4210000,
                "comment": "phone-remote",
            },
            {
                "interface": "wireguard1",
                "public-key": "aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4yZ5aB6c=",
                "endpoint-address": "203.0.113.88:51820",
                "last-handshake": "2m15s",
                "rx": 58300000,
                "tx": 14200000,
                "comment": "laptop-travel",
            },
            {
                "interface": "wireguard1",
                "public-key": "7kL8mN9oP0qR1sT2uV3wX4yZ5aB6c7d8e9f0a1b2c3d=",
                "endpoint-address": None,
                "last-handshake": None,
                "rx": 0,
                "tx": 0,
                "comment": "backup-offsite",
            },
        ]

        # Device connection bytes state: mac -> {"orig": int, "repl": int}
        self.conn_counters: dict[str, dict[str, int]] = {}
        for dev in self.synthetic_pool:
            self.conn_counters[dev["mac"]] = {
                "orig": random.randint(100000, 5000000),
                "repl": random.randint(500000, 20000000),
            }

    def _tick(self) -> float:
        now = time.time()
        dt = max(0.1, now - self.last_tick_time)
        self.last_tick_time = now
        self.step_counter += 1

        # Periodically toggle guest devices
        if self.step_counter % 25 == 0:
            guest = self.synthetic_pool[-1]
            guest["active"] = not guest["active"]
        if self.step_counter % 40 == 0:
            ipad = self.synthetic_pool[-2]
            ipad["active"] = not ipad["active"]

        return dt

    async def get_system_health(self) -> SystemHealth:
        dt = self._tick()
        t = time.time() - self.start_time

        # Sinusoidal CPU oscillation with slight noise
        cpu = int(22 + 18 * math.sin(t / 8.0) + random.uniform(-4, 5))
        cpu = max(5, min(95, cpu))

        # Temperature fluctuates between 44 and 52 C
        temp = round(47.5 + 2.5 * math.sin(t / 15.0) + random.uniform(-0.3, 0.4), 1)

        uptime = int(time.time() - self.start_time) + 3600 * 24 * 3  # ~3 days base

        # WAN current rate calculation
        active_devices = [d for d in self.synthetic_pool if d["active"]]
        total_rate = sum(d["base_rate"] for d in active_devices)
        jitter = random.uniform(0.7, 1.3)
        wan_dl = int(total_rate * jitter)
        wan_ul = int(total_rate * 0.25 * jitter)

        return SystemHealth(
            cpu_load_percent=cpu,
            free_memory_bytes=382 * 1024 * 1024,
            total_memory_bytes=512 * 1024 * 1024,
            temperature_celsius=temp,
            uptime_seconds=uptime,
            wan_download_bps=wan_dl * 8,
            wan_upload_bps=wan_ul * 8,
            active_connections_count=len(active_devices) * 12 + random.randint(5, 20),
            poll_interval_sec=2.0,
            board_name="hAP ax3",
            routeros_version="7.25",
        )

    async def get_dhcp_leases(self) -> list[dict[str, Any]]:
        leases: list[dict[str, Any]] = []
        for dev in self.synthetic_pool:
            if not dev["active"]:
                continue
            leases.append({
                "address": dev["ip"],
                "mac-address": dev["mac"],
                "host-name": dev["host-name"],
                "comment": dev["comment"],
                "status": "bound",
                "active-address": dev["ip"],
            })
        return leases

    async def get_connections(self) -> list[dict[str, Any]]:
        dt = self._tick()
        conns: list[dict[str, Any]] = []
        ext_ips = list(self.dns_records.keys())

        for dev in self.synthetic_pool:
            if not dev["active"]:
                continue

            counters = self.conn_counters[dev["mac"]]
            # Add synthetic byte increment proportional to base rate
            burst = random.uniform(0.5, 2.0)
            added_repl = int(dev["base_rate"] * dt * burst)
            added_orig = int(added_repl * 0.15)

            counters["repl"] += added_repl
            counters["orig"] += added_orig

            # Also increment WAN counters
            self.wan_rx_bytes += added_repl
            self.wan_tx_bytes += added_orig

            # Generate 2-4 active connection flows per device
            num_flows = 2 if dev["base_rate"] < 50000 else 4
            for i in range(num_flows):
                dst_ip = ext_ips[(hash(dev["ip"]) + i) % len(ext_ips)]
                proto = "tcp" if i != 1 else "udp"
                dst_port = 443 if proto == "tcp" else (53 if dst_ip == "1.1.1.1" else 443)

                conns.append({
                    "src-address": f"{dev['ip']}:{random.randint(40000, 60000)}",
                    "dst-address": f"{dst_ip}:{dst_port}",
                    "protocol": proto,
                    "dst-port": str(dst_port),
                    "orig-bytes": str(counters["orig"] // num_flows),
                    "repl-bytes": str(counters["repl"] // num_flows),
                })

        return conns

    async def get_wifi_registrations(self) -> list[dict[str, Any]]:
        regs: list[dict[str, Any]] = []
        for dev in self.synthetic_pool:
            if not dev["active"] or not dev["is_wifi"]:
                continue

            # Deterministic base signal with slight variation
            base_dbm = -50 - (hash(dev["mac"]) % 28)
            signal_dbm = base_dbm + random.randint(-2, 2)

            regs.append({
                "interface": "wifi1" if signal_dbm > -65 else "wifi2",
                "mac-address": dev["mac"],
                # Modern wifi package uses 'signal'
                "signal": signal_dbm,
                # Legacy wireless package uses 'signal-strength'
                "signal-strength": f"{signal_dbm}dBm@ht40",
                "tx-rate": "433.3Mbps-80MHz/2S/SGI",
                "rx-rate": "300.0Mbps-40MHz/2S",
            })
        return regs

    async def get_dns_cache(self) -> list[dict[str, Any]]:
        cache_entries: list[dict[str, Any]] = []
        for ip, domain in self.dns_records.items():
            cache_entries.append({
                "name": domain,
                "address": ip,
                "data": ip,
                "type": "A",
            })
        return cache_entries

    async def get_wan_counters(self) -> tuple[int, int]:
        return self.wan_rx_bytes, self.wan_tx_bytes

    async def get_wireguard_peers(self) -> list[WireGuardPeer]:
        # Increment simulated peer traffic
        peers: list[WireGuardPeer] = []
        for p in self.wg_peers:
            if p["endpoint-address"]:
                p["rx"] += random.randint(500, 8000)
                p["tx"] += random.randint(200, 3000)

            peers.append(
                WireGuardPeer(
                    interface=p["interface"],
                    public_key=p["public-key"],
                    endpoint_address=p["endpoint-address"],
                    last_handshake=p["last-handshake"],
                    rx_bytes=p["rx"],
                    tx_bytes=p["tx"],
                    comment=p["comment"],
                )
            )
        return peers

    async def close(self) -> None:
        pass
