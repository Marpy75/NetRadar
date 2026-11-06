"""RouterOS 7.25 REST API adapter with mandatory CA verification."""

import json
import os
from pathlib import Path
from typing import Any
import httpx
from pydantic import BaseModel, Field
from backend.adapters.adaptive import AdaptivePollingController
from backend.adapters.base import BaseNetworkAdapter
from backend.models.network import SystemHealth, WireGuardPeer


class RouterOSConfig(BaseModel):
    """Configuration model for MikroTik REST API access."""
    host: str
    port: int = 443
    username: str
    password: str
    ca_path: str = Field(description="Mandatory path to the router CA certificate")
    wan_interface: str = "ether1"

    @classmethod
    def from_file(cls, path: str | Path) -> "RouterOSConfig":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_env(cls, env_var: str = "NETRADAR_CONFIG") -> "RouterOSConfig":
        config_path_str = os.environ.get(env_var)
        if not config_path_str:
            raise ValueError(f"Environment variable {env_var} is not set")
        return cls.from_file(config_path_str)


class RouterOSRestAdapter(BaseNetworkAdapter):
    """Adapter for MikroTik RouterOS 7.25 REST API.

    Executes strictly read-only GET requests with .proplist query parameters.
    Enforces CA certificate verification against router's self-signed cert.
    """

    def __init__(
        self,
        config: RouterOSConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.wan_interface = config.wan_interface
        self.adaptive_controller = AdaptivePollingController()

        if client is not None:
            self.client = client
        else:
            if not config.ca_path or not Path(config.ca_path).exists():
                raise ValueError(
                    f"CA certificate path is invalid or does not exist: {config.ca_path}. "
                    "Insecure HTTPS (verify=False) is forbidden."
                )
            self.client = httpx.AsyncClient(
                base_url=f"https://{config.host}:{config.port}/rest",
                auth=(config.username, config.password),
                verify=config.ca_path,
                timeout=5.0,
            )

    async def get_system_health(self) -> SystemHealth:
        """Reads /system/resource and /system/health (temperature)."""
        # 1. System resource
        res_resp = await self.client.get(
            "/system/resource",
            params={".proplist": "cpu-load,free-memory,total-memory,uptime,board-name,version"},
        )
        res_resp.raise_for_status()
        res_data = res_resp.json()
        if isinstance(res_data, list) and res_data:
            res_item = res_data[0]
        elif isinstance(res_data, dict):
            res_item = res_data
        else:
            res_item = {}

        # 2. System health (temperature)
        temp_celsius: float | None = None
        try:
            health_resp = await self.client.get(
                "/system/health",
                params={".proplist": "name,value,type"},
            )
            if health_resp.status_code == 200:
                health_data = health_resp.json()
                items = health_data if isinstance(health_data, list) else [health_data]
                for item in items:
                    name = str(item.get("name", "")).lower()
                    if "temperature" in name:
                        try:
                            temp_celsius = float(item.get("value", 0))
                            break
                        except (ValueError, TypeError):
                            pass
        except Exception:
            temp_celsius = None

        cpu_load = int(res_item.get("cpu-load", 0))
        free_mem = int(res_item.get("free-memory", 0))
        total_mem = int(res_item.get("total-memory", 0))
        uptime_str = str(res_item.get("uptime", "0s"))
        uptime_sec = self._parse_uptime(uptime_str)
        board_name = str(res_item.get("board-name", "RouterBoard"))
        ros_ver = str(res_item.get("version", "7.25"))

        return SystemHealth(
            cpu_load_percent=cpu_load,
            free_memory_bytes=free_mem,
            total_memory_bytes=total_mem,
            temperature_celsius=temp_celsius,
            uptime_seconds=uptime_sec,
            poll_interval_sec=self.adaptive_controller.current_interval,
            board_name=board_name,
            routeros_version=ros_ver,
        )

    async def get_dhcp_leases(self) -> list[dict[str, Any]]:
        """Reads /ip/dhcp-server/lease."""
        resp = await self.client.get(
            "/ip/dhcp-server/lease",
            params={".proplist": "address,mac-address,host-name,comment,status,active-address"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]

    async def get_connections(self) -> list[dict[str, Any]]:
        """Reads /ip/firewall/connection with adaptive polling adjustment."""
        resp = await self.client.get(
            "/ip/firewall/connection",
            params={".proplist": "src-address,dst-address,protocol,dst-port,orig-bytes,repl-bytes"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else ([data] if data else [])

        # Update adaptive interval based on total connections count
        self.adaptive_controller.update(len(items))
        return items

    async def get_wifi_registrations(self) -> list[dict[str, Any]]:
        """Reads wifi/wireless registration table with dual-package support."""
        normalized: list[dict[str, Any]] = []

        # 1. Try modern /interface/wifi/registration-table
        try:
            resp = await self.client.get(
                "/interface/wifi/registration-table",
                params={".proplist": "interface,mac-address,signal,tx-rate,rx-rate"},
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else [data]
                for item in items:
                    sig = item.get("signal")
                    sig_int = int(sig) if sig is not None else -65
                    normalized.append({
                        "interface": item.get("interface", "wifi1"),
                        "mac-address": item.get("mac-address", ""),
                        "signal": sig_int,
                        "signal-strength": f"{sig_int}dBm",
                        "tx-rate": str(item.get("tx-rate", "")),
                        "rx-rate": str(item.get("rx-rate", "")),
                    })
                if normalized:
                    return normalized
        except Exception:
            pass

        # 2. Fallback to classic /interface/wireless/registration-table
        try:
            resp = await self.client.get(
                "/interface/wireless/registration-table",
                params={".proplist": "interface,mac-address,signal-strength,tx-rate,rx-rate"},
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else [data]
                for item in items:
                    sig_str = str(item.get("signal-strength", "-65dBm"))
                    # Extract numeric dBm from string like "-54dBm@ht40"
                    sig_val = -65
                    try:
                        digits = sig_str.split("dBm")[0].strip()
                        sig_val = int(digits)
                    except (ValueError, IndexError):
                        pass

                    normalized.append({
                        "interface": item.get("interface", "wlan1"),
                        "mac-address": item.get("mac-address", ""),
                        "signal": sig_val,
                        "signal-strength": sig_str,
                        "tx-rate": str(item.get("tx-rate", "")),
                        "rx-rate": str(item.get("rx-rate", "")),
                    })
        except Exception:
            pass

        return normalized

    async def get_dns_cache(self) -> list[dict[str, Any]]:
        """Reads /ip/dns/cache for domain name resolution."""
        resp = await self.client.get(
            "/ip/dns/cache",
            params={".proplist": "name,address,data"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]

    async def get_wan_counters(self) -> tuple[int, int]:
        """Reads WAN interface counters from /interface."""
        resp = await self.client.get(
            "/interface",
            params={".proplist": "name,rx-byte,tx-byte,running"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else [data]

        for item in items:
            if item.get("name") == self.wan_interface:
                rx = int(item.get("rx-byte", 0))
                tx = int(item.get("tx-byte", 0))
                return rx, tx

        return 0, 0

    async def get_wireguard_peers(self) -> list[WireGuardPeer]:
        """Reads /interface/wireguard/peers."""
        peers: list[WireGuardPeer] = []
        try:
            resp = await self.client.get(
                "/interface/wireguard/peers",
                params={".proplist": "interface,public-key,endpoint-address,last-handshake,rx,tx,comment"},
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else [data]
                for p in items:
                    if not p:
                        continue
                    peers.append(
                        WireGuardPeer(
                            interface=str(p.get("interface", "wireguard1")),
                            public_key=str(p.get("public-key", "")),
                            endpoint_address=p.get("endpoint-address"),
                            last_handshake=p.get("last-handshake"),
                            rx_bytes=int(p.get("rx", 0)),
                            tx_bytes=int(p.get("tx", 0)),
                            comment=p.get("comment"),
                        )
                    )
        except Exception:
            pass

        return peers

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        await self.client.aclose()

    @staticmethod
    def _parse_uptime(uptime_str: str) -> int:
        """Parses RouterOS uptime strings (e.g. '3d4h12m5s', '1w2d', '45m10s')."""
        import re
        total_seconds = 0
        patterns = {
            "w": 7 * 24 * 3600,
            "d": 24 * 3600,
            "h": 3600,
            "m": 60,
            "s": 1,
        }
        for unit, multiplier in patterns.items():
            match = re.search(rf"(\d+){unit}", uptime_str)
            if match:
                total_seconds += int(match.group(1)) * multiplier
        return total_seconds if total_seconds > 0 else 0
