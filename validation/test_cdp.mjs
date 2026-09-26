import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { CDP } from "./cdp.mjs";

function client(t) {
  const directory = mkdtempSync(join(tmpdir(), "omt-cdp-"));
  t.after(() => rmSync(directory, { recursive: true }));
  const cdp = Object.assign(Object.create(CDP.prototype), {
    open: Promise.resolve(), nextId: 1, pending: new Map(), events: [],
    failure: new Error("target crashed"), log: join(directory, "cdp.jsonl"),
  });
  cdp.socket = { readyState: WebSocket.OPEN, send: () => {} };
  t.after(() => cdp.fail(new Error("test cleanup"), true));
  return cdp;
}

for (const method of ["Page.navigate", "Runtime.evaluate", "Tracing.start"]) {
  test(`crash still blocks ${method}`, async (t) => {
    const cdp = client(t);
    await assert.rejects(cdp.call(method), /target crashed/);
    assert.equal(cdp.pending.size, 0);
  });
}

for (const method of ["Tracing.end", "IO.read", "IO.close"]) {
  test(`crash permits only diagnostic ${method}`, async (t) => {
    const cdp = client(t);
    cdp.socket.send = (data) => {
      const { id } = JSON.parse(data);
      const pending = cdp.pending.get(id);
      cdp.fail(new Error("another target crash"));
      assert.equal(cdp.pending.has(id), true);
      clearTimeout(pending.timer);
      cdp.pending.delete(id);
      pending.resolve({ saved: true });
    };
    assert.deepEqual(await cdp.call(method), { saved: true });
    assert.match(cdp.failure.message, /target crashed/);
  });
}

test("disconnect rejects pending diagnostics", async (t) => {
  const cdp = client(t);
  cdp.socket.send = () => cdp.fail(new Error("CDP disconnected"), true);
  await assert.rejects(cdp.call("Tracing.end"), /disconnected/);
  assert.equal(cdp.pending.size, 0);
});

test("closed transport forbids diagnostic calls", async (t) => {
  const cdp = client(t);
  cdp.socket.readyState = WebSocket.CLOSED;
  await assert.rejects(cdp.call("IO.read"), /disconnected/);
});

test("trace completion remains readable after target crash", async (t) => {
  const cdp = client(t);
  cdp.events.push({ method: "Tracing.tracingComplete", params: { stream: "trace" } });
  assert.deepEqual(await cdp.waitEvent("Tracing.tracingComplete"), { stream: "trace" });
  await assert.rejects(cdp.waitEvent("Page.loadEventFired"), /target crashed/);
});
