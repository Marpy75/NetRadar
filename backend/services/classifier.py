"""Device classification service based on DHCP comments, hostnames, MAC OUI, and randomized MAC bit."""

import json
from pathlib import Path
import re
from backend.models.network import DeviceType


class DeviceClassifier:
    """Classifies network devices by analyzing DHCP lease data and MAC characteristics."""

    def __init__(self, oui_db_path: Path | str | None = None) -> None:
        if oui_db_path is None:
            oui_db_path = Path(__file__).parent.parent / "data" / "oui_db.json"
        self.oui_db_path = Path(oui_db_path)
        self.oui_cache: dict[str, str] = self._load_oui_db()

    def _load_oui_db(self) -> dict[str, str]:
        if not self.oui_db_path.exists():
            return {}
        try:
            with open(self.oui_db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k.replace(":", "").replace("-", "").upper()[:6]: v for k, v in data.items()}
        except Exception:
            return {}

    @staticmethod
    def is_randomized_mac(mac: str) -> bool:
        """Checks if the MAC address has the Locally Administered Address (LAA) bit set."""
        if not mac:
            return False
        clean_mac = mac.replace("-", ":").strip()
        parts = clean_mac.split(":")
        if not parts:
            return False
        try:
            first_byte = int(parts[0], 16)
            # Second least significant bit of first octet: 0x02
            return (first_byte & 0x02) != 0
        except ValueError:
            return False

    def get_vendor(self, mac: str) -> str | None:
        """Resolves the manufacturer name from the local OUI database."""
        if not mac:
            return None
        clean_prefix = mac.replace(":", "").replace("-", "").strip().upper()[:6]
        return self.oui_cache.get(clean_prefix)

    def classify_by_comment(self, comment: str | None) -> DeviceType | None:
        """Priority 1: Matches explicit keywords in the DHCP lease comment."""
        if not comment:
            return None
        c = comment.lower().strip()
        if re.search(r"\b(laptop|notebook|thinkpad|macbook)\b", c):
            return DeviceType.LAPTOP
        if re.search(r"\b(desktop|pc|workstation)\b", c):
            return DeviceType.PC
        if re.search(r"\b(phone|mobile|iphone|android|galaxy|pixel|smartphone)\b", c):
            return DeviceType.PHONE
        if re.search(r"\b(tablet|ipad)\b", c):
            return DeviceType.TABLET
        if re.search(r"\b(tv|smart-?tv|appletv|chromecast|bravia|webos)\b", c):
            return DeviceType.TV
        if re.search(r"\b(printer|scanner|mfp)\b", c):
            return DeviceType.PRINTER
        if re.search(r"\b(server|nas|synology|qnap|truenas|unraid|proxmox)\b", c):
            return DeviceType.SERVER
        if re.search(r"\b(iot|esp|shelly|sonoff|tasmota|zigbee|camera|relay|plug|sensor)\b", c):
            return DeviceType.IOT
        if re.search(r"\b(router|gateway|ap|access-?point|mikrotik)\b", c):
            return DeviceType.ROUTER
        return None

    def classify_by_hostname(self, hostname: str | None) -> DeviceType | None:
        """Priority 2: Heuristic matching on device hostname."""
        if not hostname:
            return None
        h = hostname.lower().strip()

        # Mobile devices
        if any(keyword in h for keyword in ["iphone", "galaxy", "pixel", "redmi", "xiaomi", "oneplus"]):
            return DeviceType.PHONE
        if "ipad" in h or "tablet" in h:
            return DeviceType.TABLET
        if "android" in h:
            return DeviceType.PHONE

        # Computers
        if any(prefix in h for prefix in ["desktop-", "laptop-", "macbook", "imac", "thinkpad"]):
            if "laptop" in h or "macbook" in h:
                return DeviceType.LAPTOP
            return DeviceType.PC
        if h.endswith("-pc") or "-pc-" in h:
            return DeviceType.PC

        # Smart TV & Media
        if any(tv in h for tv in ["appletv", "chromecast", "smarttv", "smart-tv", "webos", "bravia"]):
            return DeviceType.TV
        if h.startswith("lg-") or h.startswith("samsung-tv"):
            return DeviceType.TV

        # Printers
        if any(pr in h for pr in ["printer", "canon", "epson", "brother", "laserjet"]):
            return DeviceType.PRINTER

        # Servers & Storage
        if any(srv in h for srv in ["synology", "qnap", "truenas", "unraid", "proxmox", "homelab"]):
            return DeviceType.SERVER
        if "server" in h:
            return DeviceType.SERVER

        # IoT devices
        if any(iot in h for iot in ["esp_", "esp-", "esp32", "esp8266", "tasmota", "shelly", "tuya", "sonoff"]):
            return DeviceType.IOT

        return None

    def classify_by_vendor(self, vendor: str | None) -> DeviceType | None:
        """Helper to deduce device type if vendor gives a strong hint."""
        if not vendor:
            return None
        v = vendor.lower()
        if "espressif" in v or "raspberry pi" in v:
            return DeviceType.IOT
        if "synology" in v or "qnap" in v:
            return DeviceType.SERVER
        if "sonos" in v or "denon" in v:
            return DeviceType.IOT
        return None

    def classify(
        self,
        comment: str | None,
        hostname: str | None,
        mac: str,
    ) -> tuple[DeviceType, str | None]:
        """Runs the full priority pipeline to determine DeviceType and vendor.

        Priority order:
        1. DHCP Lease Comment
        2. DHCP Hostname Heuristics
        3. Locally Administered / Randomized MAC Bit -> DeviceType.PHONE
        4. OUI Vendor Lookup
        5. Fallback -> DeviceType.GENERIC
        """
        vendor = self.get_vendor(mac)

        # 1. Comment priority
        from_comment = self.classify_by_comment(comment)
        if from_comment is not None:
            return from_comment, vendor

        # 2. Hostname priority
        from_hostname = self.classify_by_hostname(hostname)
        if from_hostname is not None:
            return from_hostname, vendor

        # 3. Randomized MAC bit (LAA) -> Mobile device
        if self.is_randomized_mac(mac):
            return DeviceType.PHONE, vendor or "Private MAC"

        # 4. Vendor-based hint
        from_vendor = self.classify_by_vendor(vendor)
        if from_vendor is not None:
            return from_vendor, vendor

        # 5. Fallback
        return DeviceType.GENERIC, vendor
