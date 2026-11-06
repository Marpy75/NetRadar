/**
 * Device detail card popup controller
 */
export class DeviceCard {
  constructor(cardEl) {
    this.cardEl = cardEl;
    this.currentIp = null;

    // Elements
    this.iconEl = cardEl.querySelector("#dc-icon");
    this.hostnameEl = cardEl.querySelector("#dc-hostname");
    this.statusEl = cardEl.querySelector("#dc-status");
    this.closeBtn = cardEl.querySelector("#dc-close");

    this.ipEl = cardEl.querySelector("#dc-ip");
    this.macEl = cardEl.querySelector("#dc-mac");
    this.typeEl = cardEl.querySelector("#dc-type");
    this.vendorEl = cardEl.querySelector("#dc-vendor");

    this.wifiSection = cardEl.querySelector("#dc-wifi-section");
    this.signalBars = cardEl.querySelector("#dc-signal-bars");
    this.signalDbm = cardEl.querySelector("#dc-signal-dbm");
    this.txRate = cardEl.querySelector("#dc-tx-rate");
    this.rxRate = cardEl.querySelector("#dc-rx-rate");

    this.rateRx = cardEl.querySelector("#dc-rate-rx");
    this.rateTx = cardEl.querySelector("#dc-rate-tx");
    this.totalRx = cardEl.querySelector("#dc-total-rx");
    this.totalTx = cardEl.querySelector("#dc-total-tx");

    this.destsSection = cardEl.querySelector("#dc-dests-section");
    this.destsList = cardEl.querySelector("#dc-dests-list");

    this.closeBtn.addEventListener("click", () => this.hide());
  }

  show(device) {
    if (!device) return;
    this.currentIp = device.ip;
    this.cardEl.hidden = false;
    this.update(device);
  }

  hide() {
    this.cardEl.hidden = true;
    this.currentIp = null;
  }

  update(device) {
    if (!device || device.ip !== this.currentIp) return;

    this.iconEl.src = `/icons/${device.device_type || "generic"}.svg`;
    this.hostnameEl.textContent = device.hostname || device.ip;

    const status = device.status || "active";
    this.statusEl.textContent = status;
    this.statusEl.className = `dc-status badge ${status}`;

    this.ipEl.textContent = device.ip || "--";
    this.macEl.textContent = device.mac || "--";
    this.typeEl.textContent = device.device_type || "generic";
    this.vendorEl.textContent = device.oui_vendor || "Unknown";

    // Wi-Fi signal
    if (device.wifi_signal !== null && device.wifi_signal !== undefined) {
      this.wifiSection.hidden = false;
      const sig = device.wifi_signal;
      this.signalDbm.textContent = `${sig} dBm`;

      let levelClass = "s1";
      if (sig >= -55) levelClass = "s4";
      else if (sig >= -68) levelClass = "s3";
      else if (sig >= -80) levelClass = "s2";
      this.signalBars.className = `signal-bars ${levelClass}`;

      this.txRate.textContent = device.wifi_tx_rate || "--";
      this.rxRate.textContent = device.wifi_rx_rate || "--";
    } else {
      this.wifiSection.hidden = true;
    }

    // Traffic rates
    this.rateRx.textContent = this._formatBps(device.rate_bytes_rx || 0);
    this.rateTx.textContent = this._formatBps(device.rate_bytes_tx || 0);
    this.totalRx.textContent = this._formatBytes(device.bytes_rx || 0);
    this.totalTx.textContent = this._formatBytes(device.bytes_tx || 0);

    // Top destinations
    if (device.top_destinations && device.top_destinations.length > 0) {
      this.destsSection.hidden = false;
      this.destsList.innerHTML = device.top_destinations.map(d => `
        <li class="dc-dest-item">
          <span class="dc-dest-name">${this._escape(d.domain || d.ip)}</span>
          <span class="dc-dest-bytes">${this._formatBytes(d.bytes)}</span>
        </li>
      `).join("");
    } else {
      this.destsSection.hidden = true;
      this.destsList.innerHTML = "";
    }
  }

  _formatBps(bytesPerSec) {
    const bps = bytesPerSec * 8;
    if (bps >= 1000000000) return (bps / 1000000000).toFixed(1) + " Gbps";
    if (bps >= 1000000) return (bps / 1000000).toFixed(1) + " Mbps";
    if (bps >= 1000) return (bps / 1000).toFixed(1) + " Kbps";
    return bps.toFixed(0) + " bps";
  }

  _formatBytes(bytes) {
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB";
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
    return bytes + " B";
  }

  _escape(str) {
    return String(str).replace(/[&<>"']/g, s => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    })[s]);
  }
}
