import { appendFileSync } from "node:fs";

// Preserve diagnostics after a target crash without allowing the test to continue.
const diagnosticMethods = new Set(["Tracing.end", "IO.read", "IO.close"]);

export class CDP {
  constructor(url, log) {
    this.socket = new WebSocket(url);
    this.log = log;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
    this.failure = null;
    this.open = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP open timeout")), 10000);
      this.socket.addEventListener("open", () => { clearTimeout(timer); resolve(); });
      this.socket.addEventListener("error", () => { clearTimeout(timer); reject(new Error("CDP socket error")); });
    });
    this.socket.addEventListener("close", () => this.fail(new Error("CDP disconnected"), true));
    this.socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else pending.resolve(message.result);
      } else {
        this.events.push(message);
        appendFileSync(log, JSON.stringify({ receivedMs: Date.now(), ...message }) + "\n");
        if (["Inspector.targetCrashed", "Target.targetCrashed", "Runtime.exceptionThrown"].includes(message.method)) {
          this.fail(new Error(JSON.stringify(message)));
        }
      }
    });
  }

  fail(error, disconnected = false) {
    this.failure ||= error;
    for (const [id, pending] of this.pending) {
      if (pending.diagnostic && !disconnected) continue;
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }

  async call(method, params = {}, timeout = 15000) {
    await this.open;
    const diagnostic = diagnosticMethods.has(method);
    if (this.failure && !diagnostic) throw this.failure;
    if (this.socket.readyState !== WebSocket.OPEN) throw new Error("CDP disconnected");
    const id = this.nextId++;
    appendFileSync(this.log, JSON.stringify({ sentMs: Date.now(), id, method, params }) + "\n");
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout: ${method}`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer, diagnostic });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, timeout = 15000) {
    const result = await this.call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, timeout);
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }

  async waitEvent(method, from = 0, timeout = 15000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (this.failure && method !== "Tracing.tracingComplete") throw this.failure;
      const event = this.events.slice(from).find((item) => item.method === method);
      if (event) return event.params;
      if (this.socket.readyState !== WebSocket.OPEN) throw new Error("CDP disconnected");
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    throw new Error(`Missing CDP event: ${method}`);
  }

  close() { this.socket.close(); }
}
