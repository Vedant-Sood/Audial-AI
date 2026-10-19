export class NativeBridgeClient {
  constructor(runtime, {timeout = 12000, onDisconnect = () => {}} = {}) {
    this.runtime = runtime; this.timeout = timeout; this.onDisconnect = onDisconnect;
    this.port = null; this.pending = new Map(); this.sequence = 0;
  }
  connect() {
    if (this.port) return this.port;
    const port = this.runtime.connectNative("org.audialai.bridge");
    this.port = port;
    port.onMessage.addListener(response => {
      if (this.port !== port) return;
      const pending = this.pending.get(response.id);
      if (!pending) return;
      this.pending.delete(response.id); clearTimeout(pending.timer);
      if (response.ok) pending.resolve(response.result);
      else pending.reject(new Error(response.error || "The local app rejected this request."));
    });
    port.onDisconnect.addListener(() => {
      if (this.port !== port) return;
      const reason = this.runtime.lastError?.message || "The desktop bridge disconnected.";
      if (this.port === port) this.port = null;
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer); pending.reject(new Error(reason));
      }
      this.pending.clear(); this.onDisconnect(reason);
    });
    return port;
  }
  call(message) {
    if (this.pending.size >= 8) return Promise.reject(new Error("The local bridge is busy. Audio backpressure keeps the queue bounded."));
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timer = setTimeout(() => {
        this.pending.delete(id); reject(new Error("The local app did not respond. Reconnect Audial-AI."));
      }, this.timeout);
      this.pending.set(id, {resolve, reject, timer});
      try { this.connect().postMessage({...message, id}); }
      catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }
}
