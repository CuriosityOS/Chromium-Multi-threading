import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { CDP } from "./cdp.mjs";
import { findMilestone } from "./readiness.mjs";
import { parseShell } from "./display.mjs";

// Light trace for long cases: marks, TakeOver/hand-back instants, thread names.
const LIGHT_TRACE = ["blink", "blink.user_timing"];

function pssKb(pid) {
  const match = /^Pss:\s+(\d+) kB$/m.exec(readFileSync(`/proc/${pid}/smaps_rollup`, "utf8"));
  return match ? Number(match[1]) : null;
}

// Wait for a page milestone by occurrence time (console replay safe).
async function awaitMilestone({ cdp, browser, chrome, waitFor }, name, from, notBeforeMs, timeout) {
  return waitFor(() => {
    if (chrome.exitCode !== null || chrome.signalCode !== null) throw new Error("Chromium exited");
    if (cdp.failure || browser.failure) throw cdp.failure || browser.failure;
    return findMilestone(cdp.events, { from, name, notBeforeMs });
  }, timeout);
}

export async function procSnapshot(browser, { pss = false, vram = null } = {}) {
  const { processInfo } = await browser.call("SystemInfo.getProcessInfo");
  const renderers = [];
  const gpuPid = processInfo.find((entry) => entry.type === "GPU")?.id;
  let gpu = null;
  if (pss && gpuPid) {
    try { gpu = { pid: gpuPid, pssKb: pssKb(gpuPid), ...(vram ? { vramMib: vram(gpuPid) } : {}) }; } catch (error) { if (error.code !== "ENOENT" && error.code !== "ESRCH") throw error; }
  }
  for (const process of processInfo.filter((entry) => entry.type === "renderer")) {
    const pid = process.id;
    const tasks = [];
    try {
      for (const tid of readdirSync(`/proc/${pid}/task`)) {
        try {
          const comm = readFileSync(`/proc/${pid}/task/${tid}/comm`, "utf8").trim();
          const stat = readFileSync(`/proc/${pid}/task/${tid}/stat`, "utf8");
          // Fields after the final ')' start at field 3; field 22 is starttime.
          const startTicks = stat.slice(stat.lastIndexOf(")") + 2).split(" ")[19];
          tasks.push({ pid, tid: Number(tid), comm, startTicks });
        } catch (error) { if (error.code !== "ENOENT" && error.code !== "ESRCH") throw error; }
      }
      renderers.push({ pid, tasks, ...(pss ? { pssKb: pssKb(pid) } : {}) });
    } catch (error) { if (error.code !== "ENOENT" && error.code !== "ESRCH") throw error; }
  }
  return { epochMs: Date.now(), renderers, ...(pss ? { gpu } : {}), renderThreads: renderers.flatMap((entry) => entry.tasks).filter((task) => task.comm === "BlinkRenderThread".slice(0, 15)) };
}

export function movePointer(xdo, x, y) {
  const location = () => {
    const text = xdo(["getmouselocation", "--shell"]);
    const result = parseShell(text);
    assert(Number.isInteger(result.X) && Number.isInteger(result.Y), `Invalid pointer location: ${text}`);
    return result;
  };
  const before = location();
  // --sync waits for any movement, not for this destination. The X-server
  // readback below is explicit and also handles an already-positioned pointer.
  xdo(["mousemove", String(x), String(y)]);
  const after = location();
  assert.equal(after.X, x, "XTEST pointer did not reach intended X");
  assert.equal(after.Y, y, "XTEST pointer did not reach intended Y");
  return { before, after };
}

export async function nativeInput(context) {
  const { cdp, browser, chrome, base, directory, display, root, navigate, screenshot, externalScreenshot, screenOrigin, traceStart, traceStop, waitFor } = context;
  const folder = join(directory, "input");
  mkdirSync(folder);
  const log = join(directory, "chrome.log");
  const result = { startedMs: Date.now(), logStart: statSync(log).size, completed: false };
  let tracing = false;
  const xdo = (args) => {
    const response = spawnSync("xdotool", args, { env: { ...process.env, DISPLAY: display }, encoding: "utf8", timeout: 10000 });
    appendFileSync(join(folder, "xdotool.jsonl"), JSON.stringify({ epochMs: Date.now(), args, status: response.status, signal: response.signal, error: response.error?.message, stdout: response.stdout, stderr: response.stderr }) + "\n");
    assert.equal(response.status, 0, `xdotool ${args.join(" ")}: ${response.error?.message || response.stderr}; signal=${response.signal}`);
    return response.stdout.trim();
  };
  try {
    await navigate(cdp, `${base}/queries.html?mode=input&ms=3000`);
    await cdp.call("Page.bringToFront");
    await traceStart(browser);
    tracing = true;
    result.geometry = await cdp.evaluate("validation.inputGeometry()");
    await screenshot(cdp, join(folder, "before-cdp.png"));
    externalScreenshot(join(folder, "before-x11.png"));
    const alignment = spawnSync("python3", [join(root, "alignment.py"), join(folder, "before-cdp.png"), join(folder, "before-x11.png")], { encoding: "utf8", timeout: 15000 });
    assert.equal(alignment.status, 0, alignment.stderr);
    result.alignment = JSON.parse(alignment.stdout);
    const ids = xdo(["search", "--all", "--onlyvisible", "--pid", String(chrome.pid), "--name", "^OMT Query validation"]).split("\n");
    assert.equal(ids.length, 1, "Expected exactly one matching harness X11 window");
    result.windowId = ids[0];
    xdo(["windowraise", ids[0]]);
    xdo(["windowfocus", "--sync", ids[0]]);
    await cdp.evaluate("validation.inputEvents.length = 0; performance.mark('validation:input-start'); true");
    // Capture space -> X screen space (window origin; 0,0 on Xvfb).
    result.captureOrigin = screenOrigin();
    const x = Math.round(result.geometry.x + result.alignment.x + result.captureOrigin.x);
    const y = Math.round(result.geometry.y + result.alignment.y + result.captureOrigin.y);
    // A fresh invocation and no --window: XTEST, not XSendEvent/window-stack targeting.
    result.pointer = movePointer(xdo, x, y);
    // Distinct commands identify a stuck press/release instead of hiding it in
    // one motion+click chain. Best-effort release remains on this private display.
    try {
      xdo(["mousedown", "1"]);
      await new Promise((done) => setTimeout(done, 50));
    } finally { xdo(["mouseup", "1"]); }
    result.events = await waitFor(async () => {
      const events = await cdp.evaluate("validation.inputEvents");
      return events.length >= 3 ? events : null;
    });
    assert.deepEqual(result.events.map((event) => event.type), ["mousedown", "mouseup", "click"]);
    for (const event of result.events) {
      assert.equal(event.target, "input-button");
      assert.equal(event.isTrusted, true);
      assert.equal(event.button, 0);
      assert(Math.abs(event.offsetX - result.geometry.expectedOffsetX) <= 1, "Wrong offsetX");
      assert(Math.abs(event.offsetY - result.geometry.expectedOffsetY) <= 1, "Wrong offsetY");
    }
    result.focused = await cdp.evaluate("document.activeElement.id");
    assert.equal(result.focused, "input-button");
    await cdp.evaluate("performance.mark('validation:input-end'); true");
    await screenshot(cdp, join(folder, "after-cdp.png"));
    externalScreenshot(join(folder, "after-x11.png"));
    await traceStop(browser, folder);
    tracing = false;
    result.completed = true;
  } catch (error) { result.error = String(error.stack || error); throw error; }
  finally {
    if (tracing) { try { await traceStop(browser, folder); } catch (error) { result.traceError = String(error); } }
    result.finishedMs = Date.now();
    result.logEnd = statSync(log).size;
    writeFileSync(join(folder, "input.json"), JSON.stringify(result, null, 2));
  }
}

export async function pageThreads(context) {
  const { cdp, browser, base, directory, port, mode, navigate, screenshot, externalScreenshot, traceStart, traceStop, waitFor, sockets } = context;
  const folder = join(directory, "page-threads");
  mkdirSync(folder);
  const log = join(directory, "chrome.log");
  const result = { startedMs: Date.now(), logStart: statSync(log).size, mode, stages: [], completed: false };
  let tracing = false;
  let peer;
  let peerTarget;
  const save = () => writeFileSync(join(folder, "threads.json"), JSON.stringify(result, null, 2));
  const panelState = () => cdp.evaluate(`(() => {
    const panel = document.getElementById("panel");
    const rect = panel.getBoundingClientRect();
    return { height: panel.offsetHeight, token: panel.dataset.historyToken || null, rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height } };
  })()`);
  async function panelShot(name) {
    // Settling is outside every measured busy block. The analyzer checks actual
    // external pixels and rejects stale A/B surfaces, rather than trusting time.
    await new Promise((done) => setTimeout(done, 250));
    externalScreenshot(join(folder, `${name}-x11.png`));
    await screenshot(cdp, join(folder, `${name}-cdp.png`));
  }
  async function stage(name, count) {
    let previous = "";
    let stable = 0;
    const snapshot = await waitFor(async () => {
      const current = await procSnapshot(browser);
      appendFileSync(join(folder, "proc-samples.jsonl"), JSON.stringify({ stage: name, ...current }) + "\n");
      const key = JSON.stringify(current.renderThreads);
      stable = key === previous ? stable + 1 : 0;
      previous = key;
      return current.renderThreads.length === (mode === "omt" ? count : 0) && stable >= 3 ? current : null;
    }, 20000);
    result.stages.push({ name, logEnd: statSync(log).size, ...snapshot });
    save();
    return snapshot;
  }
  try {
    await traceStart(browser);
    tracing = true;
    result.urlA = `${base}/a.html?page=owner-a`;
    result.urlPeer = `${base}/a.html?page=peer`;
    result.urlB = `${base}/b.html?page=owner-b`;
    await navigate(cdp, result.urlA);
    await cdp.evaluate("performance.mark('validation:page-a'); true");
    const first = await stage("one-page", 1);
    const opened = await cdp.call("Runtime.evaluate", { expression: `window.validationPeer = window.open(${JSON.stringify(result.urlPeer)}, 'validation-peer'); Boolean(window.validationPeer)`, userGesture: true, returnByValue: true });
    assert.equal(opened.result?.value, true, "Same-origin window.open was blocked");
    peerTarget = await waitFor(async () => {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(5000) });
      return (await response.json()).find((target) => target.type === "page" && target.url === result.urlPeer);
    });
    peer = new CDP(peerTarget.webSocketDebuggerUrl, join(folder, "peer-cdp.jsonl"));
    sockets.push(peer);
    await peer.call("Runtime.enable");
    await peer.call("Page.enable");
    await peer.call("Inspector.enable");
    await waitFor(() => peer.evaluate("window.validationReady === true"));
    await peer.evaluate("performance.mark('validation:page-peer'); true");
    const two = await stage("two-pages", 2);
    if (mode === "omt") {
      assert.equal(new Set(two.renderThreads.map((thread) => thread.pid)).size, 1, "Pages did not share one renderer PID");
      assert(two.renderThreads.some((thread) => thread.tid === first.renderThreads[0].tid), "Owner thread disappeared on window.open");
    }
    result.peerCloseStartedMs = Date.now();
    await browser.call("Target.closeTarget", { targetId: peerTarget.id });
    peerTarget = null;
    const closed = await stage("peer-closed", 1);
    if (mode === "omt") assert.deepEqual(closed.renderThreads, first.renderThreads, "Closing peer did not restore original owner thread");
    result.bfcache = { expectedToken: `owner-a:${result.startedMs}` };
    await cdp.evaluate(`(() => {
      const panel = document.getElementById("panel");
      panel.style.transition = "none";
      panel.style.height = "64px";
      panel.dataset.historyToken = ${JSON.stringify(result.bfcache.expectedToken)};
      return true;
    })()`);
    result.bfcache.original = await panelState();
    assert.equal(result.bfcache.original.height, 64);
    await panelShot("owner-a");
    result.navigationStartedMs = Date.now();
    await navigate(cdp, result.urlB);
    await cdp.evaluate("performance.mark('validation:page-b'); true");
    const replaced = await stage("owner-navigated", 1);
    if (mode === "omt") assert.notDeepEqual(replaced.renderThreads, first.renderThreads, "Navigation reused the old document's thread");
    result.bfcache.onB = await panelState();
    assert.equal(result.bfcache.onB.height, 24);
    assert.equal(result.bfcache.onB.token, null);
    await panelShot("owner-b");
    const eventOffset = cdp.events.length;
    result.historyBackStartedMs = Date.now();
    await cdp.evaluate("performance.mark('validation:history-back-start'); history.back(); true");
    result.bfcache.pageshow = await waitFor(() => {
      if (cdp.failure || browser.failure) throw cdp.failure || browser.failure;
      return findMilestone(cdp.events, {
        from: eventOffset, name: "pageshow", notBeforeMs: result.historyBackStartedMs,
        accept: (value) => value.url === result.urlA,
      });
    }, 30000);
    result.bfcache.notUsed = cdp.events.slice(eventOffset).filter((event) => event.method === "Page.backForwardCacheNotUsed");
    assert.equal(result.bfcache.pageshow.persisted, true, "History navigation missed BFCache; restore path unproven");
    await cdp.evaluate("performance.mark('validation:page-a-restored'); true");
    const restored = await stage("owner-restored", 1);
    if (mode === "omt") {
      assert.notDeepEqual(restored.renderThreads, first.renderThreads, "BFCache reused the stopped A render thread");
      assert.notDeepEqual(restored.renderThreads, replaced.renderThreads, "BFCache reused B's render thread");
    }
    result.bfcache.restored = await panelState();
    assert.equal(result.bfcache.restored.height, 64, "Restored offsetHeight lost the cached DOM mutation");
    assert.equal(result.bfcache.restored.token, result.bfcache.expectedToken, "History navigation lost A's DOM identity");
    await panelShot("restored-a");
    // Idle restored pages render on main. Prove the NEW thread by a mutation +
    // long synchronous task (timer task, not a debugger evaluation) => TakeOver.
    const blockOffset = cdp.events.length;
    const blockArmedMs = Date.now();
    await cdp.evaluate("setTimeout(() => validation.restoredBlock(600), 0); true");
    result.bfcache.block = await awaitMilestone(context, "restored-block-end", blockOffset, blockArmedMs, 15000);
    assert.deepEqual(result.bfcache.block.reads, [96, 96], "Restored in-block offsetHeight reads wrong");
    result.bfcache.mutated = await panelState();
    assert.equal(result.bfcache.mutated.height, 96, "Restored page did not answer a fresh geometry mutation");
    await panelShot("restored-mutated-a");
    await cdp.evaluate("performance.mark('validation:history-back-end'); true");
    await traceStop(browser, folder);
    tracing = false;
    result.completed = true;
  } catch (error) { result.error = String(error.stack || error); throw error; }
  finally {
    if (peerTarget) { try { await browser.call("Target.closeTarget", { targetId: peerTarget.id }); } catch (error) { result.closeError = String(error); } }
    peer?.close();
    if (tracing) { try { await traceStop(browser, folder); } catch (error) { result.traceError = String(error); } }
    result.finishedMs = Date.now();
    result.logEnd = statSync(log).size;
    save();
  }
}

// OMT only: a page the replica cannot reproduce must detach and render stock.
export async function unreplicable(context) {
  const { cdp, browser, base, directory, mode, navigate, externalScreenshot, traceStart, traceStop } = context;
  if (mode !== "omt") return;
  const folder = join(directory, "unreplicable");
  mkdirSync(folder);
  const log = join(directory, "chrome.log");
  const result = { startedMs: Date.now(), logStart: statSync(log).size, ms: 1000, completed: false };
  let tracing = false;
  try {
    await traceStart(browser);
    tracing = true;
    await navigate(cdp, `${base}/unreplicable.html?mode=unreplicable&kind=height&ms=${result.ms}`);
    result.before = await cdp.evaluate("validation.geometry()");
    assert.equal(result.before.panelHeight, 24);
    const offset = cdp.events.length;
    const armedMs = Date.now();
    await cdp.evaluate(`setTimeout(() => validation.runBlock(${result.ms}), 200); true`);
    result.block = await awaitMilestone(context, "block-result", offset, armedMs, result.ms + 15000);
    await new Promise((done) => setTimeout(done, result.ms * 0.8 + 600));
    result.after = await cdp.evaluate("validation.geometry()");
    assert(Math.abs(result.after.panelHeight - 264) < 1, "Unreplicable page final layout height missing");
    assert(Math.abs(result.after.followerTop - result.before.followerTop - 240) < 1, "Unreplicable page sibling did not move");
    externalScreenshot(join(folder, "after-x11.png"));
    await traceStop(browser, folder);
    tracing = false;
    result.completed = true;
  } catch (error) { result.error = String(error.stack || error); throw error; }
  finally {
    if (tracing) { try { await traceStop(browser, folder); } catch (error) { result.traceError = String(error); } }
    result.finishedMs = Date.now();
    result.logEnd = statSync(log).size;
    writeFileSync(join(folder, "unreplicable.json"), JSON.stringify(result, null, 2));
  }
}

// Short-task churn then idle; sample every renderer's PSS. The analyzer picks
// the page's renderer by the trace-mark PID (no guessing while live).
export async function memoryChurn(context) {
  const { cdp, browser, base, directory, navigate, traceStart, traceStop, vram } = context;
  const folder = join(directory, "mem");
  mkdirSync(folder);
  const log = join(directory, "chrome.log");
  const result = { startedMs: Date.now(), logStart: statSync(log).size, churnMs: 20000, idleMs: 25000, intervalMs: 2000, samples: [], completed: false };
  let tracing = false;
  try {
    await traceStart(browser, LIGHT_TRACE);
    tracing = true;
    await navigate(cdp, `${base}/mem.html`);
    const offset = cdp.events.length;
    result.churnStart = await cdp.evaluate(`validation.startChurn(${result.churnMs})`);
    for (let index = 0; index * result.intervalMs <= result.churnMs + result.idleMs; index++) {
      const due = result.churnStart.epochMs + index * result.intervalMs;
      await new Promise((done) => setTimeout(done, Math.max(0, due - Date.now())));
      if (cdp.failure || browser.failure) throw cdp.failure || browser.failure;
      const snapshot = await procSnapshot(browser, { pss: true, vram });
      result.samples.push({ epochMs: snapshot.epochMs, gpu: snapshot.gpu, renderers: snapshot.renderers.map(({ pid, pssKb, tasks }) => ({ pid, pssKb, renderThreads: tasks.filter((task) => task.comm === "BlinkRenderThread".slice(0, 15)).length })) });
    }
    result.churnEnd = await awaitMilestone(context, "churn-end", offset, result.churnStart.epochMs, 5000);
    await traceStop(browser, folder);
    tracing = false;
    result.completed = true;
  } catch (error) { result.error = String(error.stack || error); throw error; }
  finally {
    if (tracing) { try { await traceStop(browser, folder); } catch (error) { result.traceError = String(error); } }
    result.finishedMs = Date.now();
    result.logEnd = statSync(log).size;
    writeFileSync(join(folder, "memory.json"), JSON.stringify(result, null, 2));
  }
}
