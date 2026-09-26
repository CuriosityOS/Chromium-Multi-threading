import assert from "node:assert/strict";
import test from "node:test";
import { findMilestone, waitForResize } from "./readiness.mjs";

const event = (value) => ({ method: "Runtime.consoleAPICalled", params: { args: [{ value: `VALIDATION ${JSON.stringify(value)}` }] } });
const options = { name: "pageshow", notBeforeMs: 200, accept: (value) => value.url === "a" };

test("BFCache console replay cannot substitute for a fresh pageshow", () => {
  const stale = event({ name: "pageshow", epochMs: 100, persisted: false, url: "a" });
  const fresh = event({ name: "pageshow", epochMs: 201, persisted: true, url: "a" });
  assert.equal(findMilestone([stale], options), null);
  assert.equal(findMilestone([stale, fresh], options).persisted, true);
});

test("pageshow requires the correct URL and a finite occurrence timestamp", () => {
  const events = [
    event({ name: "pageshow", epochMs: 201, url: "b" }),
    event({ name: "pageshow", url: "a" }),
    event({ name: "pageshow", epochMs: "201", url: "a" }),
    event({ name: "ready", epochMs: 201, url: "a" }),
  ];
  assert.equal(findMilestone(events, options), null);
});

test("fresh cache miss is returned for explicit failure, never filtered out", () => {
  const missed = { name: "pageshow", epochMs: 202, persisted: false, url: "a" };
  assert.deepEqual(findMilestone([event(missed)], options), missed);
});

const before = { width: 1279, height: 651 };
const after = { width: 1080, height: 572 };
const bounded = async (condition) => {
  for (let i = 0; i < 4; i++) {
    const value = await condition();
    if (value) return value;
  }
  throw new Error("bounded readiness timeout");
};

test("resize waits for geometry AND its matching delayed event", async () => {
  let calls = 0;
  const cdp = {
    events: [],
    async evaluate() {
      calls++;
      if (calls === 1) return before;
      if (calls === 3) this.events.push(event({ name: "resize", epochMs: 201, width: 1080, height: 651 }));
      if (calls === 4) this.events.push(event({ name: "resize", epochMs: 202, ...after }));
      return after;
    },
  };
  const ready = await waitForResize(cdp, bounded, before, 0, 200);
  assert.equal(calls, 4);
  assert.deepEqual(ready.geometry, after);
  assert.equal(ready.milestone.epochMs, 202);
});

test("resize geometry alone is insufficient; failed polls retain diagnostics", async () => {
  const cdp = { events: [], evaluate: async () => after };
  const samples = [];
  await assert.rejects(waitForResize(cdp, bounded, before, 0, 200, (sample) => samples.push(sample)), /readiness timeout/);
  assert.equal(samples.length, 4);
  assert(samples.every((sample) => Number.isFinite(sample.observedMs) && sample.milestone === null));
  assert.deepEqual(samples.at(-1).geometry, after);
});

test("resize event alone is insufficient", async () => {
  const cdp = { events: [event({ name: "resize", epochMs: 201, ...after })], evaluate: async () => before };
  await assert.rejects(waitForResize(cdp, bounded, before, 0, 200), /readiness timeout/);
});
