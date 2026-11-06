"""Abstract Base Adapter for network state collectors."""

from abc import ABC, abstractmethod
from typing import Any
from backend.models.network import SystemHealth, WireGuardPeer


class BaseNetworkAdapter(ABC):
    """Abstract interface for network state sources (Simulator and RouterOS REST)."""

    @abstractmethod
    async def get_system_health(self) -> SystemHealth:
        """Retrieves system health metrics (CPU, RAM, temperature, uptime)."""
        pass

    @abstractmethod
    async def get_dhcp_leases(self) -> list[dict[str, Any]]:
        """Retrieves current DHCP leases from the router."""
        pass

    @abstractmethod
    async def get_connections(self) -> list[dict[str, Any]]:
        """Retrieves firewall tracking connections table."""
        pass

    @abstractmethod
    async def get_wifi_registrations(self) -> list[dict[str, Any]]:
        """Retrieves registered wireless/wifi clients (signal and rates)."""
        pass

    @abstractmethod
    async def get_dns_cache(self) -> list[dict[str, Any]]:
        """Retrieves DNS cache entries (mapping IP -> domain names)."""
        pass

    @abstractmethod
    async def get_wan_counters(self) -> tuple[int, int]:
        """Retrieves cumulative WAN interface traffic counters (rx_bytes, tx_bytes)."""
        pass

    @abstractmethod
    async def get_wireguard_peers(self) -> list[WireGuardPeer]:
        """Retrieves list of WireGuard peers and tunnel state."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Gracefully releases resources, connection pools, or background tasks."""
        pass
