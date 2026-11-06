/**
 * WebSocket client with automatic reconnection
 */
export class WsClient {
  constructor(path = "/ws") {
    this.path = path;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 10000;
    this.baseReconnectDelay = 1000;
    this.reconnectTimer = null;
    this.listeners = {
      message: [],
      status: []
    };
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const url = `${protocol}//${host}${this.path}`;

    this._notifyStatus("connecting");

    try {
      this.ws = new WebSocket(url);
    } catch (err) {
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this._notifyStatus("connected");
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this._notifyMessage(data);
      } catch (err) {
        // Ignore parse error
      }
    };

    this.ws.onclose = () => {
      this._notifyStatus("disconnected");
      this._scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws.close();
    };
  }

  onMessage(callback) {
    this.listeners.message.push(callback);
  }

  onStatusChange(callback) {
    this.listeners.status.push(callback);
  }

  _notifyMessage(data) {
    for (const cb of this.listeners.message) {
      cb(data);
    }
  }

  _notifyStatus(status) {
    for (const cb of this.listeners.status) {
      cb(status);
    }
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) {
      return;
    }
    const delay = Math.min(
      this.baseReconnectDelay * Math.pow(1.5, this.reconnectAttempts),
      this.maxReconnectDelay
    );
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}
