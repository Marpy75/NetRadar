"""Unit tests for DeviceClassifier service."""

import pytest
from backend.models.network import DeviceType
from backend.services.classifier import DeviceClassifier


@pytest.fixture
def classifier() -> DeviceClassifier:
    return DeviceClassifier()


class TestDeviceClassifier:
    def test_classify_by_comment_priority(self, classifier: DeviceClassifier):
        # Comment should override hostname and MAC
        dtype, vendor = classifier.classify(
            comment="office laptop",
            hostname="DESKTOP-ABC",
            mac="00:11:32:00:11:22",  # Synology OUI
        )
        assert dtype == DeviceType.LAPTOP

        dtype, _ = classifier.classify(comment="living room tv", hostname="device1", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.TV

        dtype, _ = classifier.classify(comment="kitchen lights iot", hostname=None, mac="00:00:00:00:00:00")
        assert dtype == DeviceType.IOT

        dtype, _ = classifier.classify(comment="network storage server", hostname=None, mac="00:00:00:00:00:00")
        assert dtype == DeviceType.SERVER

        dtype, _ = classifier.classify(comment="workstation pc", hostname=None, mac="00:00:00:00:00:00")
        assert dtype == DeviceType.PC

        dtype, _ = classifier.classify(comment="office printer", hostname=None, mac="00:00:00:00:00:00")
        assert dtype == DeviceType.PRINTER

    def test_classify_by_hostname_priority(self, classifier: DeviceClassifier):
        # No comment, hostname should dictate
        dtype, _ = classifier.classify(comment=None, hostname="iPhone-15-Pro", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.PHONE

        dtype, _ = classifier.classify(comment=None, hostname="Galaxy-S24-Ultra", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.PHONE

        dtype, _ = classifier.classify(comment=None, hostname="MacBook-Air-M3", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.LAPTOP

        dtype, _ = classifier.classify(comment=None, hostname="DESKTOP-89F123", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.PC

        dtype, _ = classifier.classify(comment=None, hostname="synology-nas", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.SERVER

        dtype, _ = classifier.classify(comment=None, hostname="ESP32-Sensor-Living", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.IOT

        dtype, _ = classifier.classify(comment=None, hostname="HP-LaserJet-M404", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.PRINTER

        dtype, _ = classifier.classify(comment=None, hostname="LG-webOSTV-4K", mac="00:00:00:00:00:00")
        assert dtype == DeviceType.TV

    def test_randomized_mac_bit_detection(self, classifier: DeviceClassifier):
        # 0xDA is binary 11011010 -> second bit from right is 1 (0x02) -> randomized!
        assert classifier.is_randomized_mac("DA:A1:19:44:81:22") is True
        # 0x02 is binary 00000010 -> randomized!
        assert classifier.is_randomized_mac("02:BF:33:44:55:66") is True
        # 0xF0 is binary 11110000 -> bit 1 is 0 -> not randomized
        assert classifier.is_randomized_mac("F0:18:98:2A:4C:11") is False
        # 0x00 is binary 00000000 -> not randomized
        assert classifier.is_randomized_mac("00:11:32:88:99:AA") is False

        # If no comment and generic hostname, randomized MAC classifies as mobile phone
        dtype, vendor = classifier.classify(comment=None, hostname="unknown-device", mac="DA:A1:19:44:81:22")
        assert dtype == DeviceType.PHONE
        assert "Private" in (vendor or "")

    def test_oui_vendor_lookup(self, classifier: DeviceClassifier):
        # F0:18:98 is Apple
        vendor = classifier.get_vendor("F0:18:98:2A:4C:11")
        assert vendor == "Apple"

        # 00:11:32 is Synology
        vendor = classifier.get_vendor("00:11:32:88:99:AA")
        assert vendor == "Synology"

        # 24:0A:C4 is Espressif
        vendor = classifier.get_vendor("24:0A:C4:AA:BB:CC")
        assert vendor == "Espressif Inc."

        # 48:2C:67 is MikroTik
        vendor = classifier.get_vendor("48:2C:67:12:34:56")
        assert vendor == "MikroTik"

    def test_oui_vendor_based_type_deduction(self, classifier: DeviceClassifier):
        # Espressif MAC without comments or hints should classify as IOT
        dtype, vendor = classifier.classify(comment=None, hostname="device-xyz", mac="24:0A:C4:AA:BB:CC")
        assert dtype == DeviceType.IOT
        assert vendor == "Espressif Inc."

        # Synology MAC without comments or hints should classify as SERVER
        dtype, vendor = classifier.classify(comment=None, hostname="storage", mac="00:11:32:88:99:AA")
        assert dtype == DeviceType.SERVER
        assert vendor == "Synology"

    def test_fallback_to_generic(self, classifier: DeviceClassifier):
        # Unknown non-randomized MAC with generic name
        dtype, vendor = classifier.classify(comment=None, hostname="node-42", mac="40:00:00:11:22:33")
        assert dtype == DeviceType.GENERIC
        assert vendor is None
