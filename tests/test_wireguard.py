"""Unit tests for WireGuard service, RouterOS commands, and QR generation."""

import base64
from pathlib import Path
import pytest
from backend.services.wireguard import (
    WireGuardAddPeerRequest,
    WireGuardFinalizeRequest,
    WireGuardInitRequest,
    WireGuardService,
)


class TestWireGuardService:
    def test_key_pair_generation(self):
        pair1 = WireGuardService.generate_key_pair()
        pair2 = WireGuardService.generate_key_pair()

        # WireGuard keys are 32 bytes raw -> 44 characters base64
        assert len(pair1.private_key) == 44
        assert len(pair1.public_key) == 44
        assert len(pair2.private_key) == 44
        assert len(pair2.public_key) == 44

        # Validate base64 decodability
        raw_priv = base64.b64decode(pair1.private_key)
        raw_pub = base64.b64decode(pair1.public_key)
        assert len(raw_priv) == 32
        assert len(raw_pub) == 32

        # Keys must be random and distinct
        assert pair1.private_key != pair2.private_key
        assert pair1.public_key != pair2.public_key

    def test_init_new_interface(self):
        req = WireGuardInitRequest(
            interface_name="wg0",
            listen_port=51820,
            tunnel_subnet="10.10.0.0/24",
            client_ip="10.10.0.2/32",
            server_endpoint="vpn.myhome.net:51820",
            allowed_ips=["10.10.0.0/24", "10.20.0.0/24"],
            dns="10.20.0.1",
        )
        res = WireGuardService.init_new_interface(req)

        assert len(res.client_private_key) == 44
        assert len(res.client_public_key) == 44
        assert len(res.routeros_commands) == 5

        # All commands must have comment="netradar"
        for cmd in res.routeros_commands:
            assert 'comment="netradar"' in cmd

        # 1. Interface add
        assert '/interface/wireguard add name="wg0" listen-port=51820' in res.routeros_commands[0]

        # 2. IP address add
        assert '/ip/address add address=10.10.0.1/24 interface="wg0"' in res.routeros_commands[1]

        # 3. Interface list member
        assert '/interface/list/member add list=LAN interface="wg0"' in res.routeros_commands[2]

        # 4. Firewall filter with place-before=0
        fw_cmd = res.routeros_commands[3]
        assert "/ip/firewall/filter add chain=input action=accept protocol=udp dst-port=51820" in fw_cmd
        assert "place-before=0" in fw_cmd

        # 5. Peers add
        peer_cmd = res.routeros_commands[4]
        assert f'/interface/wireguard/peers add interface="wg0" public-key="{res.client_public_key}"' in peer_cmd
        assert "allowed-address=10.10.0.2/32" in peer_cmd

    def test_finalize_new_interface(self):
        priv_key = WireGuardService.generate_key_pair().private_key
        server_pub = WireGuardService.generate_key_pair().public_key

        req = WireGuardFinalizeRequest(
            client_private_key=priv_key,
            server_public_key=server_pub,
            client_ip="10.10.0.2/24",
            server_endpoint="vpn.myhome.net:51820",
            allowed_ips=["10.10.0.0/24", "10.20.0.0/24"],
            dns="10.20.0.1",
        )
        res = WireGuardService.finalize_new_interface(req)

        # Check client config content
        conf = res.client_config_text
        assert "[Interface]" in conf
        assert f"PrivateKey = {priv_key}" in conf
        assert "Address = 10.10.0.2/24" in conf
        assert "DNS = 10.20.0.1" in conf
        assert "[Peer]" in conf
        assert f"PublicKey = {server_pub}" in conf
        assert "Endpoint = vpn.myhome.net:51820" in conf
        assert "AllowedIPs = 10.10.0.0/24, 10.20.0.0/24" in conf
        assert "PersistentKeepalive = 25" in conf

        # Check SVG QR code
        assert "<svg" in res.qr_svg
        assert "</svg>" in res.qr_svg

    def test_add_peer_to_existing(self):
        server_pub = WireGuardService.generate_key_pair().public_key
        req = WireGuardAddPeerRequest(
            interface_name="wireguard1",
            server_public_key=server_pub,
            client_ip="10.10.0.5/32",
            server_endpoint="vpn.example.com:13231",
            allowed_ips=["0.0.0.0/0"],
            dns="1.1.1.1",
        )
        res = WireGuardService.add_peer_to_existing(req)

        assert len(res.client_private_key) == 44
        assert len(res.client_public_key) == 44

        # RouterOS command check
        assert '/interface/wireguard/peers add interface="wireguard1"' in res.routeros_command
        assert f'public-key="{res.client_public_key}"' in res.routeros_command
        assert 'allowed-address=10.10.0.5/32' in res.routeros_command
        assert 'comment="netradar"' in res.routeros_command

        # Config and QR
        assert f"PrivateKey = {res.client_private_key}" in res.client_config_text
        assert f"PublicKey = {server_pub}" in res.client_config_text
        assert "<svg" in res.qr_svg

    def test_no_disk_persistence(self, tmp_path: Path):
        # Ensure that running wireguard operations does not write files to disk
        initial_files = list(Path(".").glob("**/*.key")) + list(Path(".").glob("**/*.conf"))
        assert len(initial_files) == 0

        req = WireGuardInitRequest()
        res_init = WireGuardService.init_new_interface(req)
        fin_req = WireGuardFinalizeRequest(
            client_private_key=res_init.client_private_key,
            server_public_key="some_server_public_key_value_123456789012=",
        )
        _ = WireGuardService.finalize_new_interface(fin_req)

        remaining_files = list(Path(".").glob("**/*.key")) + list(Path(".").glob("**/*.conf"))
        assert len(remaining_files) == 0
