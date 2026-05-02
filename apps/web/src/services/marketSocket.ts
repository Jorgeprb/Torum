import type { MarketMessage, Timeframe } from "./market";
import { marketWebSocketUrl } from "./market";

export type MarketSocketStatus = "connecting" | "connected" | "reconnecting" | "disconnected" | "stale";

interface MarketSocketManagerOptions {
  onMessage: (message: MarketMessage) => void;
  onStatusChange: (status: MarketSocketStatus) => void;
  onReconnect?: () => void;
  heartbeatMs?: number;
  staleAfterMs?: number;
  maxBackoffMs?: number;
}

export class MarketSocketManager {
  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private staleTimer: number | null = null;
  private reconnectAttempts = 0;
  private closedByUser = false;
  private symbol: string | null = null;
  private timeframe: Timeframe | null = null;
  private status: MarketSocketStatus = "disconnected";
  private lastMessageAt = 0;
  private lastPongAt = 0;
  private readonly heartbeatMs: number;
  private readonly staleAfterMs: number;
  private readonly maxBackoffMs: number;

  constructor(private readonly options: MarketSocketManagerOptions) {
    this.heartbeatMs = options.heartbeatMs ?? 5000;
    this.staleAfterMs = options.staleAfterMs ?? 45000;
    this.maxBackoffMs = options.maxBackoffMs ?? 5000;
  }

  connect(symbol: string, timeframe: Timeframe) {
    this.symbol = symbol;
    this.timeframe = timeframe;
    this.closedByUser = false;
    this.openSocket("connecting");
  }

  disconnect() {
    this.closedByUser = true;
    this.clearTimers();
    if (this.socket) {
      this.socket.onopen = null;
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      this.socket.close();
    }
    this.socket = null;
    this.setStatus("disconnected");
  }

  ensureFresh(reason = "ensureFresh") {
    if (this.closedByUser) {
      return;
    }
    const lastActivityAt = Math.max(this.lastMessageAt, this.lastPongAt);
    const stale = Date.now() - lastActivityAt > this.staleAfterMs;
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || stale) {
      this.reconnect(reason);
    }
  }

  reconnectNow(_reason = "manual") {
    if (this.closedByUser) {
      return;
    }

    this.reconnectAttempts = 0;
    this.openSocket("reconnecting");
  }

  markOffline() {
    this.setStatus("disconnected");
  }

  getStatus() {
    return this.status;
  }

  getLastMessageAt() {
    return this.lastMessageAt;
  }

  getLastPongAt() {
    return this.lastPongAt;
  }

  private openSocket(status: MarketSocketStatus) {
    if (!this.symbol || !this.timeframe) {
      return;
    }
    this.clearTimers();
    if (this.socket) {
      this.socket.onopen = null;
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      this.socket.close();
    }
    this.setStatus(status);
    const socket = new WebSocket(marketWebSocketUrl(this.symbol, this.timeframe));
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.lastMessageAt = Date.now();
      this.setStatus("connected");
      this.startHeartbeat();
      this.options.onReconnect?.();
    };

    socket.onmessage = (event) => {
      this.lastMessageAt = Date.now();
      let message: MarketMessage;
      try {
        message = JSON.parse(event.data) as MarketMessage;
      } catch {
        return;
      }
      if (message.type === "pong") {
        this.lastPongAt = Date.now();
        return;
      }
      if (this.status === "stale") {
        this.setStatus("connected");
      }
      this.options.onMessage(message);
    };

    socket.onerror = () => {
      this.reconnect("error");
    };

    socket.onclose = () => {
      if (!this.closedByUser) {
        this.reconnect("close");
      }
    };
  }

  private reconnect(_reason: string) {
    if (this.closedByUser) {
      return;
    }
    this.clearTimers();
    if (this.socket) {
      this.socket.onopen = null;
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      this.socket.close();
      this.socket = null;
    }
    this.setStatus("reconnecting");
    const delay = this.nextBackoffDelay();
    this.reconnectTimer = window.setTimeout(() => this.openSocket("reconnecting"), delay);
  }

  private nextBackoffDelay() {
    const base = Math.min(this.maxBackoffMs, 250 * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    const jitter = Math.floor(Math.random() * 150);
    return Math.min(this.maxBackoffMs, base + jitter);
  }

  private startHeartbeat() {
    this.heartbeatTimer = window.setInterval(() => {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        this.reconnect("heartbeat-not-open");
        return;
      }
      this.socket.send(JSON.stringify({ type: "ping", ts: Date.now() }));
    }, this.heartbeatMs);

    this.staleTimer = window.setInterval(() => {
      const lastActivityAt = Math.max(this.lastMessageAt, this.lastPongAt);
      if (Date.now() - lastActivityAt > this.staleAfterMs) {
        this.setStatus("stale");
        this.reconnect("stale");
      }
    }, Math.max(5000, Math.floor(this.staleAfterMs / 2)));
  }

  private clearTimers() {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.staleTimer !== null) {
      window.clearInterval(this.staleTimer);
      this.staleTimer = null;
    }
  }

  private setStatus(status: MarketSocketStatus) {
    if (this.status === status) {
      return;
    }
    this.status = status;
    this.options.onStatusChange(status);
  }
}
