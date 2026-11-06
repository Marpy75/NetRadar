/**
 * WireGuard Configuration Wizard
 */
export class WireGuardWizard {
  constructor(modalEl, btnTrigger) {
    this.modalEl = modalEl;
    this.btnTrigger = btnTrigger;

    this.closeBtn = modalEl.querySelector("#wg-close");
    this.tabBtns = modalEl.querySelectorAll(".tab-btn");
    this.tabNewIface = modalEl.querySelector("#tab-new-iface");
    this.tabAddPeer = modalEl.querySelector("#tab-add-peer");

    // New interface elements
    this.step1El = modalEl.querySelector("#wg-step1");
    this.step2El = modalEl.querySelector("#wg-step2");
    this.step1Btn = modalEl.querySelector("#wg-step1-btn");
    this.step2Btn = modalEl.querySelector("#wg-step2-btn");
    this.step2BackBtn = modalEl.querySelector("#wg-step2-back");
    this.step1Result = modalEl.querySelector("#wg-step1-result");
    this.commandsPre = modalEl.querySelector("#wg-commands");
    this.copyCmdsBtn = modalEl.querySelector("#wg-copy-cmds");
    this.clientPubSpan = modalEl.querySelector("#wg-client-pub");

    // Add peer elements
    this.apGenerateBtn = modalEl.querySelector("#ap-generate-btn");

    // Shared result elements
    this.resultEl = modalEl.querySelector("#wg-result");
    this.resultCommand = modalEl.querySelector("#result-command");
    this.resultCopyCmd = modalEl.querySelector("#result-copy-cmd");
    this.resultConf = modalEl.querySelector("#result-conf");
    this.resultCopyConf = modalEl.querySelector("#result-copy-conf");
    this.resultQr = modalEl.querySelector("#result-qr");
    this.resultNewBtn = modalEl.querySelector("#result-new");

    // In-memory state (never stored to localStorage or disk)
    this._step1Data = null;

    this._bindEvents();
  }

  _bindEvents() {
    this.btnTrigger.addEventListener("click", () => this.show());
    this.closeBtn.addEventListener("click", () => this.hide());

    // Tabs
    this.tabBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        this.tabBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        if (tab === "new-iface") {
          this.tabNewIface.hidden = false;
          this.tabAddPeer.hidden = true;
        } else {
          this.tabNewIface.hidden = true;
          this.tabAddPeer.hidden = false;
        }
        this._resetResults();
      });
    });

    // Step 1: Generate initial commands
    this.step1Btn.addEventListener("click", () => this._handleStep1());

    // Copy step 1 commands
    this.copyCmdsBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(this.commandsPre.textContent);
    });

    // Step 2: Finalize interface
    this.step2Btn.addEventListener("click", () => this._handleStep2());
    this.step2BackBtn.addEventListener("click", () => {
      this.step2El.hidden = true;
      this.step1El.hidden = false;
    });

    // Add peer generate
    this.apGenerateBtn.addEventListener("click", () => this._handleAddPeer());

    // Result actions
    this.resultCopyCmd.addEventListener("click", () => {
      navigator.clipboard.writeText(this.resultCommand.textContent);
    });
    this.resultCopyConf.addEventListener("click", () => {
      navigator.clipboard.writeText(this.resultConf.textContent);
    });
    this.resultNewBtn.addEventListener("click", () => {
      this._resetResults();
      this.step1El.hidden = false;
      this.step2El.hidden = true;
    });
  }

  show() {
    this.modalEl.hidden = false;
    this._resetResults();
  }

  hide() {
    this.modalEl.hidden = true;
    this._step1Data = null; // Clear sensitive keys from memory
  }

  _resetResults() {
    this._step1Data = null;
    this.step1Result.hidden = true;
    this.step2El.hidden = true;
    this.step1El.hidden = false;
    this.resultEl.hidden = true;
    this.resultQr.innerHTML = "";
  }

  async _handleStep1() {
    const payload = {
      interface_name: this.modalEl.querySelector("#wg-iface-name").value.trim(),
      listen_port: parseInt(this.modalEl.querySelector("#wg-listen-port").value, 10),
      tunnel_subnet: this.modalEl.querySelector("#wg-tunnel-subnet").value.trim(),
      client_ip: this.modalEl.querySelector("#wg-client-ip").value.trim(),
      endpoint: this.modalEl.querySelector("#wg-endpoint").value.trim(),
      allowed_ips: this.modalEl.querySelector("#wg-allowed-ips").value.trim(),
      dns: this.modalEl.querySelector("#wg-dns").value.trim()
    };

    try {
      const res = await fetch("/api/wireguard/init-interface", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      this._step1Data = {
        ...payload,
        client_private_key: data.client_private_key,
        client_public_key: data.client_public_key
      };

      this.commandsPre.textContent = data.routeros_commands;
      this.clientPubSpan.textContent = data.client_public_key;
      this.step1Result.hidden = false;

      // Show step 2
      this.step2El.hidden = false;
    } catch (err) {
      alert("Failed to initialize WireGuard interface: " + err.message);
    }
  }

  async _handleStep2() {
    const serverPub = this.modalEl.querySelector("#wg-server-pub").value.trim();
    if (!serverPub) {
      alert("Please enter the router public key.");
      return;
    }

    if (!this._step1Data) {
      alert("Session expired. Please restart Step 1.");
      return;
    }

    const payload = {
      client_private_key: this._step1Data.client_private_key,
      server_public_key: serverPub,
      client_ip: this._step1Data.client_ip,
      endpoint: this._step1Data.endpoint,
      allowed_ips: this._step1Data.allowed_ips,
      dns: this._step1Data.dns
    };

    try {
      const res = await fetch("/api/wireguard/finalize-interface", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      this._showFinalResult("", data.client_config, data.qr_svg);
    } catch (err) {
      alert("Failed to finalize WireGuard configuration: " + err.message);
    }
  }

  async _handleAddPeer() {
    const payload = {
      interface_name: this.modalEl.querySelector("#ap-iface-name").value.trim(),
      server_public_key: this.modalEl.querySelector("#ap-server-pub").value.trim(),
      client_ip: this.modalEl.querySelector("#ap-client-ip").value.trim(),
      endpoint: this.modalEl.querySelector("#ap-endpoint").value.trim(),
      allowed_ips: this.modalEl.querySelector("#ap-allowed-ips").value.trim(),
      dns: this.modalEl.querySelector("#ap-dns").value.trim()
    };

    if (!payload.server_public_key) {
      alert("Please enter the server public key.");
      return;
    }

    try {
      const res = await fetch("/api/wireguard/add-peer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      this._showFinalResult(data.routeros_commands, data.client_config, data.qr_svg);
    } catch (err) {
      alert("Failed to create WireGuard peer: " + err.message);
    }
  }

  _showFinalResult(command, conf, qrSvg) {
    this.step1El.hidden = true;
    this.step2El.hidden = true;
    this.tabAddPeer.hidden = true;
    this.resultEl.hidden = false;

    if (command) {
      this.resultCommand.textContent = command;
      this.resultCommand.parentElement.hidden = false;
    } else {
      this.resultCommand.textContent = "";
      this.resultCommand.parentElement.hidden = true;
    }

    this.resultConf.textContent = conf;
    this.resultQr.innerHTML = qrSvg;
  }
}
