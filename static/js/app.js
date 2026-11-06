import { WsClient } from "./ws-client.js";
import { NetworkGraph } from "./network-graph.js";
import { DeviceCard } from "./device-card.js";
import { WireGuardWizard } from "./wireguard-wizard.js";

/**
 * Main NetRadar Application Entry
 */
class NetRadarApp {
  constructor() {
    this.wsClient = new WsClient("/ws");

    // UI Elements
    this.wsDot = document.getElementById("ws-dot");
    this.wsStatus = document.getElementById("ws-status");
    this.modeBadge = document.getElementById("mode-badge");

    // Health
    this.cpuBar = document.getElementById("cpu-bar");
    this.cpuVal = document.getElementById("cpu-val");
    this.ramBar = document.getElementById("ram-bar");
    this.ramVal = document.getElementById("ram-val");
    this.tempVal = document.getElementById("temp-val");
    this.uptimeVal = document.getElementById("uptime-val");
    this.boardVal = document.getElementById("board-val");

    // WAN Sparkline
    this.wanDl = document.getElementById("wan-dl");
    this.wanUl = document.getElementById("wan-ul");
    this.connCount = document.getElementById("conn-count");
    this.chartDl = document.getElementById("wan-chart-dl");
    this.chartUl = document.getElementById("wan-chart-ul");

    this.dlHistory = new Array(40).fill(0);
    this.ulHistory = new Array(40).fill(0);

    // Lists
    this.topDevicesList = document.getElementById("top-devices-list");
    this.wgPeerList = document.getElementById("wg-peer-list");
    this.eventList = document.getElementById("event-list");

    // Subsystems
    this.deviceCard = new DeviceCard(document.getElementById("device-card"));
    this.graph = new NetworkGraph(
      document.getElementById("graph-container"),
      (device) => this.deviceCard.show(device)
    );

    const wgModal = document.getElementById("wg-modal");
    const btnWg = document.getElementById("btn-wg-wizard");
    this.wgWizard = new WireGuardWizard(wgModal, btnWg);

    this._bindEvents();
  }

  start() {
    this.wsClient.onStatusChange((status) => this._onWsStatus(status));
    this.wsClient.onMessage((frame) => this._onFrame(frame));
    this.wsClient.connect();
  }

  _bindEvents() {
    // Escape key closes modals
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        this.deviceCard.hide();
        this.wgWizard.hide();
      }
    });
  }

  _onWsStatus(status) {
    if (status === "connected") {
      this.wsDot.className = "status-dot connected";
      this.wsStatus.textContent = "Connected";
    } else if (status === "connecting") {
      this.wsDot.className = "status-dot";
      this.wsStatus.textContent = "Connecting...";
    } else {
      this.wsDot.className = "status-dot disconnected";
      this.wsStatus.textContent = "Disconnected";
    }
  }

  _onFrame(frame) {
    if (!frame) return;

    // 1. Health & Mode
    if (frame.health) {
      this._updateHealth(frame.health);
    }

    // 2. WAN & Sparkline
    if (frame.wan) {
      this._updateWan(frame.wan, frame.health?.active_connections);
    }

    // 3. Graph & Particles
    if (frame.devices) {
      this.graph.updateData(frame.devices, frame.flows);

      // Keep open device card updated
      if (this.deviceCard.currentIp) {
        const d = frame.devices.find(x => x.ip === this.deviceCard.currentIp);
        if (d) this.deviceCard.update(d);
      }

      this._updateTopDevices(frame.devices);
    }

    // 4. WireGuard Peers
    if (frame.wireguard_peers) {
      this._updateWireguard(frame.wireguard_peers);
    }

    // 5. Events Log
    if (frame.events) {
      this._updateEvents(frame.events);
    }
  }

  _updateHealth(h) {
    const cpu = Math.round(h.cpu_load || 0);
    this.cpuBar.style.width = `${Math.min(100, cpu)}%`;
    this.cpuVal.textContent = `${cpu}%`;

    const totalRam = h.total_memory || 1;
    const freeRam = h.free_memory || 0;
    const ramPct = Math.round(((totalRam - freeRam) / totalRam) * 100);
    this.ramBar.style.width = `${Math.min(100, Math.max(0, ramPct))}%`;
    this.ramVal.textContent = `${ramPct}%`;

    this.tempVal.textContent = h.temperature !== null ? `${h.temperature} C` : "--";
    this.uptimeVal.textContent = this._formatUptime(h.uptime_seconds || 0);
    this.boardVal.textContent = h.board_name || "RouterOS";
  }

  _updateWan(wan, conns) {
    const dlBps = wan.rate_rx_bps || 0;
    const ulBps = wan.rate_tx_bps || 0;

    this.wanDl.textContent = this._formatBps(dlBps / 8);
    this.wanUl.textContent = this._formatBps(ulBps / 8);
    this.connCount.textContent = `${conns || 0} conn`;

    // Shift sparkline
    this.dlHistory.shift();
    this.dlHistory.push(dlBps);
    this.ulHistory.shift();
    this.ulHistory.push(ulBps);

    this._renderSparkline();
  }

  _renderSparkline() {
    const maxVal = Math.max(100000, ...this.dlHistory, ...this.ulHistory);
    const w = 200;
    const h = 50;
    const n = this.dlHistory.length;

    const dlPoints = this.dlHistory.map((val, i) => {
      const x = (i / (n - 1)) * w;
      const y = h - (val / maxVal) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");

    const ulPoints = this.ulHistory.map((val, i) => {
      const x = (i / (n - 1)) * w;
      const y = h - (val / maxVal) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");

    this.chartDl.setAttribute("points", dlPoints);
    this.chartUl.setAttribute("points", ulPoints);
  }

  _updateTopDevices(devices) {
    const active = devices
      .filter(d => d.status !== "offline")
      .map(d => ({
        ...d,
        totalRate: (d.rate_bytes_rx || 0) + (d.rate_bytes_tx || 0)
      }))
      .sort((a, b) => b.totalRate - a.totalRate)
      .slice(0, 5);

    this.topDevicesList.innerHTML = active.map(d => `
      <li class="device-rank-item" data-ip="${d.ip}">
        <span class="name">${this._escape(d.hostname || d.ip)}</span>
        <span class="rate">${this._formatBps(d.totalRate)}</span>
      </li>
    `).join("");

    this.topDevicesList.querySelectorAll(".device-rank-item").forEach(item => {
      item.addEventListener("click", () => {
        const ip = item.dataset.ip;
        const dev = devices.find(d => d.ip === ip);
        if (dev) this.deviceCard.show(dev);
      });
    });
  }

  _updateWireguard(peers) {
    if (!peers || peers.length === 0) {
      this.wgPeerList.innerHTML = `<li class="wg-peer-item"><span class="wg-peer-time">No peers active</span></li>`;
      return;
    }

    this.wgPeerList.innerHTML = peers.map(p => `
      <li class="wg-peer-item">
        <div class="wg-peer-info">
          <span class="wg-peer-ip">${this._escape(p.allowed_address || p.interface)}</span>
          <span class="wg-peer-time">${this._formatHandshake(p.last_handshake_seconds)}</span>
        </div>
        <div class="wg-peer-rates">
          <div>${this._formatBytes(p.rx_bytes)} RX</div>
          <div>${this._formatBytes(p.tx_bytes)} TX</div>
        </div>
      </li>
    `).join("");
  }

  _updateEvents(events) {
    const recent = [...events].reverse().slice(0, 20);
    this.eventList.innerHTML = recent.map(e => `
      <li class="event-item ${this._escape(e.event_type)}">
        <span class="event-time">${this._formatTime(e.timestamp)}</span>
        <span class="event-desc">${this._escape(e.description)}</span>
      </li>
    `).join("");
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

  _formatUptime(sec) {
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  _formatHandshake(sec) {
    if (sec === null || sec === undefined) return "Never";
    if (sec < 60) return `${sec}s ago`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    return `${Math.floor(sec / 3600)}h ago`;
  }

  _formatTime(isoString) {
    if (!isoString) return "";
    const d = new Date(isoString);
    return d.toTimeString().split(" ")[0];
  }

  _escape(str) {
    return String(str || "").replace(/[&<>"']/g, s => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    })[s]);
  }
}

// Bootstrap
document.addEventListener("DOMContentLoaded", () => {
  const app = new NetRadarApp();
  app.start();
});
