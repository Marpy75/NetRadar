"""WireGuard service for X25519 key generation, RouterOS 7.25 commands, and SVG QR generation."""

import base64
import io
import ipaddress
from typing import Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from pydantic import BaseModel, Field
import segno


class WireGuardKeyPair(BaseModel):
    private_key: str
    public_key: str


class WireGuardInitRequest(BaseModel):
    interface_name: str = "wireguard1"
    listen_port: int = 13231
    tunnel_subnet: str = "10.10.0.0/24"
    client_ip: str = "10.10.0.2/32"
    server_endpoint: str = "vpn.example.home:13231"
    allowed_ips: list[str] = Field(default_factory=lambda: ["10.10.0.0/24", "10.20.0.0/24"])
    dns: str = "10.20.0.1"


class WireGuardInitResponse(BaseModel):
    client_private_key: str
    client_public_key: str
    routeros_commands: list[str]


class WireGuardFinalizeRequest(BaseModel):
    client_private_key: str
    server_public_key: str
    client_ip: str = "10.10.0.2/24"
    server_endpoint: str = "vpn.example.home:13231"
    allowed_ips: list[str] = Field(default_factory=lambda: ["10.10.0.0/24", "10.20.0.0/24"])
    dns: str = "10.20.0.1"


class WireGuardFinalizeResponse(BaseModel):
    client_config_text: str
    qr_svg: str


class WireGuardAddPeerRequest(BaseModel):
    interface_name: str = "wireguard1"
    server_public_key: str
    client_ip: str = "10.10.0.3/32"
    server_endpoint: str = "vpn.example.home:13231"
    allowed_ips: list[str] = Field(default_factory=lambda: ["10.10.0.0/24", "10.20.0.0/24"])
    dns: str = "10.20.0.1"


class WireGuardAddPeerResponse(BaseModel):
    client_private_key: str
    client_public_key: str
    routeros_command: str
    client_config_text: str
    qr_svg: str


class WireGuardService:
    """Handles X25519 key generation, RouterOS 7.25 command templating, and QR generation."""

    @staticmethod
    def generate_key_pair() -> WireGuardKeyPair:
        """Generates an X25519 key pair. Private key is never persisted to disk or logs."""
        private_key = x25519.X25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return WireGuardKeyPair(
            private_key=base64.b64encode(private_bytes).decode("ascii"),
            public_key=base64.b64encode(public_bytes).decode("ascii"),
        )

    @staticmethod
    def generate_qr_svg(content: str) -> str:
        """Generates a standalone SVG QR-code using the segno library."""
        qr = segno.make_qr(content)
        buffer = io.BytesIO()
        qr.save(buffer, kind="svg", scale=4, dark="#1c1e24", light="#ffffff")
        return buffer.getvalue().decode("utf-8")

    @classmethod
    def build_client_config(
        cls,
        client_private_key: str,
        server_public_key: str,
        client_ip: str,
        server_endpoint: str,
        allowed_ips: list[str],
        dns: str,
    ) -> str:
        """Constructs standard WireGuard client configuration file (.conf)."""
        allowed_ips_str = ", ".join(allowed_ips)
        # Ensure client_ip has CIDR notation for the Interface section
        ip_entry = client_ip if "/" in client_ip else f"{client_ip}/24"

        config_lines = [
            "[Interface]",
            f"PrivateKey = {client_private_key.strip()}",
            f"Address = {ip_entry}",
            f"DNS = {dns.strip()}",
            "",
            "[Peer]",
            f"PublicKey = {server_public_key.strip()}",
            f"Endpoint = {server_endpoint.strip()}",
            f"AllowedIPs = {allowed_ips_str}",
            "PersistentKeepalive = 25",
            "",
        ]
        return "\n".join(config_lines)

    @classmethod
    def init_new_interface(cls, req: WireGuardInitRequest) -> WireGuardInitResponse:
        """Step 1 of new interface creation: generates keys and RouterOS 7.25 setup commands."""
        keys = cls.generate_key_pair()

        # Derive server gateway IP (first usable IP of tunnel subnet)
        net = ipaddress.ip_network(req.tunnel_subnet, strict=False)
        server_ip = f"{net.network_address + 1}/{net.prefixlen}"

        # Clean client_ip representation
        client_ip_entry = req.client_ip if "/" in req.client_ip else f"{req.client_ip}/32"

        commands = [
            f'/interface/wireguard add name="{req.interface_name}" listen-port={req.listen_port} comment="netradar"',
            f'/ip/address add address={server_ip} interface="{req.interface_name}" comment="netradar"',
            f'/interface/list/member add list=LAN interface="{req.interface_name}" comment="netradar"',
            f'/ip/firewall/filter add chain=input action=accept protocol=udp dst-port={req.listen_port} place-before=0 comment="netradar"',
            f'/interface/wireguard/peers add interface="{req.interface_name}" public-key="{keys.public_key}" allowed-address={client_ip_entry} comment="netradar"',
        ]

        return WireGuardInitResponse(
            client_private_key=keys.private_key,
            client_public_key=keys.public_key,
            routeros_commands=commands,
        )

    @classmethod
    def finalize_new_interface(cls, req: WireGuardFinalizeRequest) -> WireGuardFinalizeResponse:
        """Step 2 of new interface creation: binds server public key to client config and QR."""
        config_text = cls.build_client_config(
            client_private_key=req.client_private_key,
            server_public_key=req.server_public_key,
            client_ip=req.client_ip,
            server_endpoint=req.server_endpoint,
            allowed_ips=req.allowed_ips,
            dns=req.dns,
        )
        qr_svg = cls.generate_qr_svg(config_text)
        return WireGuardFinalizeResponse(
            client_config_text=config_text,
            qr_svg=qr_svg,
        )

    @classmethod
    def add_peer_to_existing(cls, req: WireGuardAddPeerRequest) -> WireGuardAddPeerResponse:
        """Single-step flow for adding a new peer to an existing WireGuard interface."""
        keys = cls.generate_key_pair()
        client_ip_entry = req.client_ip if "/" in req.client_ip else f"{req.client_ip}/32"

        routeros_cmd = (
            f'/interface/wireguard/peers add interface="{req.interface_name}" '
            f'public-key="{keys.public_key}" allowed-address={client_ip_entry} comment="netradar"'
        )

        config_text = cls.build_client_config(
            client_private_key=keys.private_key,
            server_public_key=req.server_public_key,
            client_ip=req.client_ip,
            server_endpoint=req.server_endpoint,
            allowed_ips=req.allowed_ips,
            dns=req.dns,
        )
        qr_svg = cls.generate_qr_svg(config_text)

        return WireGuardAddPeerResponse(
            client_private_key=keys.private_key,
            client_public_key=keys.public_key,
            routeros_command=routeros_cmd,
            client_config_text=config_text,
            qr_svg=qr_svg,
        )
