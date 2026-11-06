"""Pydantic schemas for NetRadar network state and monitoring."""

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class DeviceType(str, Enum):
    ROUTER = "router"
    LAPTOP = "laptop"
    PC = "pc"
    PHONE = "phone"
    TABLET = "tablet"
    IOT = "iot"
    TV = "tv"
    PRINTER = "printer"
    SERVER = "server"
    GENERIC = "generic"


class DeviceStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    OFFLINE = "offline"


class TransportProtocol(str, Enum):
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    OTHER = "other"


class TopDestination(BaseModel):
    destination: str
    domain: str | None = None
    protocol: TransportProtocol
    bytes_count: int
    connections_count: int


class DeviceNode(BaseModel):
    id: str
    ip: str
    mac: str
    hostname: str | None = None
    comment: str | None = None
    device_type: DeviceType = DeviceType.GENERIC
    vendor: str | None = None
    status: DeviceStatus = DeviceStatus.CONNECTED
    wifi_signal_dbm: int | None = None
    wifi_tx_rate: str | None = None
    wifi_rx_rate: str | None = None
    rate_rx_bps: int = 0
    rate_tx_bps: int = 0
    total_rx_bytes: int = 0
    total_tx_bytes: int = 0
    last_seen: float
    top_destinations: list[TopDestination] = Field(default_factory=list)


class TrafficFlow(BaseModel):
    client_ip: str
    destination_ip: str
    destination_domain: str | None = None
    protocol: TransportProtocol
    dst_port: int
    bytes_per_sec: int
    packets_per_sec: int = 0


class SystemHealth(BaseModel):
    cpu_load_percent: int
    free_memory_bytes: int
    total_memory_bytes: int
    temperature_celsius: float | None = None
    uptime_seconds: int
    wan_download_bps: int = 0
    wan_upload_bps: int = 0
    active_connections_count: int = 0
    poll_interval_sec: float = 2.0
    board_name: str
    routeros_version: str


class WireGuardPeer(BaseModel):
    interface: str
    public_key: str
    endpoint_address: str | None = None
    last_handshake: str | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0
    comment: str | None = None


class NetworkEvent(BaseModel):
    timestamp: float
    event_type: str
    description: str


class NetworkStateFrame(BaseModel):
    timestamp: float
    system: SystemHealth
    devices: list[DeviceNode]
    flows: list[TrafficFlow]
    events: list[NetworkEvent] = Field(default_factory=list)
    wireguard_peers: list[WireGuardPeer] = Field(default_factory=list)
