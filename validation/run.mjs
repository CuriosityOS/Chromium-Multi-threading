#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { appendFileSync, closeSync, existsSync, mkdirSync, openSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { CDP } from "./cdp.mjs";
import { fingerprintBuild } from "./build.mjs";
import { captureArgs } from "./media.mjs";
import { memoryChurn, nativeInput, pageThreads, unreplicable } from "./extended.mjs";
import { waitForResize } from "./readiness.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const cli = process.argv.slice(2);
const approved = cli.includes("--build-ready");
if (!approved) {
  console.error("REFUSED: parent must confirm build ready; then pass --build-ready. No Chromium was launched.");
  process.exit(2);
}
if (process.platform !== "linux") throw new Error("Run on Linux (ssh core)");
const option = (key, fallback) => cli.includes(key) ? cli[cli.indexOf(key) + 1] : fallback;
const binary = resolve(option("--binary", "/root/cr153/src/out/Omt/chrome"));
const output = resolve(option("--output", join(root, "results", new Date().toISOString().replaceAll(":", "-"))));
const traceThread = option("--render-thread", "^BlinkRenderThread$");
const traceEvent = option("--render-event", "^ReplicaPage::(BeginFrame|Paint)$");
const expectedVersion = "153.0.8010.55";
const UNREPLICABLE_IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
async function buildSnapshot(label) {
  const manifest = await fingerprintBuild(binary);
  writeFileSync(join(output, `build-${label}.json`), JSON.stringify(manifest, null, 2));
  return manifest;
}
mkdirSync(output, { recursive: true });
if (existsSync(join(output, "run.json"))) throw new Error("Output already contains a run; choose a new directory");
// Parent-confirmed: unthrottled blink instant event at every journal-attached
// main-thread style/layout entry, including calls when the lifecycle is clean.
const fallbackTraceEvent = "RenderThreadJournal::MainThreadFallback";
// Schema 3: hybrid hand-off / hand-back model (TakeOver, BeginHandBack, HandBack, StopPresenting).
const run = { schemaVersion: 3, binary, expectedVersion, output, traceThread, traceEvent, fallbackTraceEvent, startedMs: Date.now(), cases: [], failures: [] };
const save = () => writeFileSync(join(output, "run.json"), JSON.stringify(run, null, 2) + "\n");
save();
const children = new Set();
const sockets = [];
let server;
let shuttingDown = false;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

function launch(command, args, log, extra = {}) {
  appendFileSync(join(output, "commands.jsonl"), JSON.stringify({ epochMs: Date.now(), command, args }) + "\n");
  const fd = openSync(log, "a");
  const child = spawn(command, args, { stdio: ["ignore", fd, fd], detached: true, ...extra });
  closeSync(fd);
  child.failure = null;
  child.on("error", (error) => { child.failure = error; });
  children.add(child);
  return child;
}

function alive(child, name) {
  if (child.failure) throw child.failure;
  if (child.exitCode !== null || child.signalCode !== null) throw new Error(`${name} exited: ${child.exitCode}/${child.signalCode}`);
}

async function waitFor(check, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await check();
    if (value) return value;
    await sleep(50);
  }
  throw new Error("Missing readiness milestone / timeout");
}

async function stop(child, signal = "SIGTERM") {
  if (!child) return;
  if (child.pid) {
    // Also clean up this private group's descendants if its parent already crashed.
    try { process.kill(-child.pid, signal); } catch (error) { if (error.code !== "ESRCH") throw error; }
    const deadline = Date.now() + 5000;
    while (child.exitCode === null && child.signalCode === null && Date.now() < deadline) await sleep(50);
    // Only this harness's private process group, never pkill chrome/Xvfb.
    try { process.kill(-child.pid, "SIGKILL"); } catch (error) { if (error.code !== "ESRCH") throw error; }
  }
  children.delete(child);
}

async function cleanup() {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const socket of sockets) socket.close();
  for (const child of [...children].reverse()) await stop(child);
  server?.close();
}

for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, async () => {
  run.failures.push(`Interrupted: ${signal}`);
  save();
  await cleanup();
  process.exit(1);
});

async function screenshot(cdp, path) {
  const image = await cdp.call("Page.captureScreenshot", { format: "png", fromSurface: true });
  writeFileSync(path, Buffer.from(image.data, "base64"));
}

function externalScreenshot(display, path) {
  const capture = spawnSync("ffmpeg", ["-nostdin", "-y", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x800", "-i", display, "-frames:v", "1", "-threads", "1", path], { timeout: 10000, encoding: "utf8" });
  assert.equal(capture.status, 0, capture.stderr);
}

async function navigate(cdp, url) {
  const offset = cdp.events.length;
  // Cold profile navigation exceeded 15s in the first approved baseline run.
  // This is readiness only: block duration and every evidence gate are unchanged.
  const result = await cdp.call("Page.navigate", { url }, 60000);
  assert(!result.errorText, result.errorText);
  await cdp.waitEvent("Page.loadEventFired", offset, 60000);
  await waitFor(() => cdp.evaluate("window.validationReady === true"));
  await sleep(700); // BEFORE-state settling only; never between class change and block.
}

const FULL_TRACE = ["toplevel", "blink", "blink.user_timing", "devtools.timeline", "cc", "viz", "gpu", "v8", "omt", "disabled-by-default-blink.debug", "disabled-by-default-devtools.timeline"];
async function traceStart(browser, includedCategories = FULL_TRACE) {
  await browser.call("Tracing.start", {
    transferMode: "ReturnAsStream", streamFormat: "json",
    traceConfig: { recordMode: "recordContinuously", includedCategories },
  });
}

async function traceStop(browser, directory) {
  const offset = browser.events.length;
  await browser.call("Tracing.end");
  const completed = await browser.waitEvent("Tracing.tracingComplete", offset, 30000);
  writeFileSync(join(directory, "trace-complete.json"), JSON.stringify(completed, null, 2));
  assert(completed.stream, "Trace stream missing");
  const fd = openSync(join(directory, "trace.json"), "w");
  try {
    for (;;) {
      const chunk = await browser.call("IO.read", { handle: completed.stream, size: 1024 * 1024 });
      appendFileSync(fd, Buffer.from(chunk.data, chunk.base64Encoded ? "base64" : "utf8"));
      if (chunk.eof) break;
    }
  } finally { closeSync(fd); }
  await browser.call("IO.close", { handle: completed.stream });
  assert(!completed.dataLossOccurred, "Trace data loss; cannot prove render-thread evidence");
}

async function smoke(cdp, browser, target, base, directory, display) {
  await navigate(cdp, `${base}/index.html?mode=smoke`);
  const steps = ["insert", "remove", "text", "inline", "cssom-insert", "cssom-delete"];
  const results = [];
  await screenshot(cdp, join(directory, "smoke-before-cdp.png"));
  externalScreenshot(display, join(directory, "smoke-before-x11.png"));
  // Idle mutations: main renders; the replica only follows (analyzed per mode).
  const traceFolder = join(directory, "smoke-trace");
  mkdirSync(traceFolder);
  await traceStart(browser);
  let tracing = true;
  try {
    for (const step of steps) {
      const result = await cdp.evaluate(`validation.smoke(${JSON.stringify(step)})`);
      results.push(result);
      writeFileSync(join(directory, "smoke.json"), JSON.stringify(results, null, 2));
      if (step === "insert") assert.equal(result.inserted, true);
      if (step === "remove") assert.equal(result.inserted, false);
      if (step === "text") assert.equal(result.text, "AFTER: text mutation");
      if (step === "inline") {
        assert.equal(result.inlineColor, "rgb(40, 200, 80)");
        assert.equal(result.inlineHeight, 45);
      }
      if (step.startsWith("cssom")) {
        assert.equal(result.ruleCount, step === "cssom-insert" ? 1 : 0);
        assert.equal(result.cssomColor, step === "cssom-insert" ? "rgb(130, 80, 220)" : "rgb(60, 50, 40)");
      }
      await sleep(250);
      await screenshot(cdp, join(directory, `smoke-${step}-cdp.png`));
      externalScreenshot(display, join(directory, `smoke-${step}-x11.png`));
    }
    await traceStop(browser, traceFolder);
    tracing = false;
  } finally { if (tracing) await traceStop(browser, traceFolder).catch(() => {}); }
  const before = await cdp.evaluate("validation.geometry()");
  const window = await browser.call("Browser.getWindowForTarget", { targetId: target.id });
  const eventOffset = cdp.events.length;
  const resize = { before, originalBounds: window.bounds, startedMs: Date.now() };
  let after;
  try {
    await browser.call("Browser.setWindowBounds", { windowId: window.windowId, bounds: { width: 1080, height: 720 } });
    const ready = await waitForResize(cdp, waitFor, before, eventOffset, resize.startedMs, (sample) => {
      resize.lastSample = sample;
      appendFileSync(join(directory, "resize-samples.jsonl"), JSON.stringify(sample) + "\n");
    });
    after = ready.geometry;
    resize.after = after;
    resize.milestone = ready.milestone;
    await screenshot(cdp, join(directory, "resize-cdp.png"));
  } catch (error) { resize.error = String(error.stack || error); throw error; }
  finally {
    try {
      await browser.call("Browser.setWindowBounds", { windowId: window.windowId, bounds: { width: window.bounds.width, height: window.bounds.height } });
      resize.restored = await waitFor(async () => {
        const value = await cdp.evaluate("validation.geometry()");
        return value.width === before.width && value.height === before.height ? value : null;
      });
    } catch (error) { resize.restoreError = String(error.stack || error); throw error; }
    finally { writeFileSync(join(directory, "resize.json"), JSON.stringify(resize, null, 2)); }
  }
  const blankOffset = cdp.events.length;
  await cdp.call("Page.navigate", { url: "about:blank" });
  await cdp.waitEvent("Page.loadEventFired", blankOffset);
  assert.equal(await cdp.evaluate("location.href"), "about:blank");
  await navigate(cdp, `${base}/index.html?mode=navigation-return`);
  assert.equal(await cdp.evaluate("document.title"), "Independent rendering validation");
  await screenshot(cdp, join(directory, "navigation-return-cdp.png"));
  writeFileSync(join(directory, "lifecycle.json"), JSON.stringify({ before, after, navigationReturned: true }, null, 2));
}

async function caseRun({ cdp, browser, chrome, base, mode, kind, ms, display, directory }) {
  const name = `${kind}-${ms}`;
  const caseDir = join(directory, name);
  mkdirSync(caseDir);
  const chromeLog = join(directory, "chrome.log");
  const item = { mode, kind, ms, directory: caseDir, startedMs: Date.now(), logStart: statSync(chromeLog).size, completed: false };
  run.cases.push(item);
  save();
  let recorder;
  let tracing = false;
  try {
    await traceStart(browser);
    tracing = true;
    await navigate(cdp, `${base}/${kind === "queries" ? "queries.html" : "index.html"}?mode=${mode}&kind=${kind}&ms=${ms}`);
    item.before = await cdp.evaluate("validation.geometry()");
    assert.equal(item.before.dpr, 1, "Capture assumes 1 device pixel per CSS pixel");
    assert.equal(item.before.panelHeight, 24);
    await screenshot(cdp, join(caseDir, "before-cdp.png"));
    const captureLog = join(caseDir, "ffmpeg.log");
    const progress = join(caseDir, "ffmpeg-progress.log");
    item.captureStartedMs = Date.now();
    recorder = launch("ffmpeg", captureArgs(display, join(caseDir, "capture.mkv"), progress), captureLog);
    await waitFor(() => {
      alive(chrome, "Chromium"); alive(recorder, "ffmpeg");
      return existsSync(progress) && /frame=\s*[1-9]/.test(readFileSync(progress, "utf8"));
    });
    await sleep(600);
    item.dispatchedMs = Date.now();
    const eventOffset = cdp.events.length;
    // Arm a normal timer task; do not execute the block in a debugger evaluation.
    // No further renderer commands until its console result arrives.
    const viewport = { width: item.before.width, height: item.before.height };
    await cdp.evaluate(`setTimeout(() => validation.runBlock(${ms}, ${JSON.stringify(viewport)}), 200); true`);
    item.block = await waitFor(() => {
      alive(chrome, "Chromium"); alive(recorder, "ffmpeg");
      if (cdp.failure || browser.failure) throw cdp.failure || browser.failure;
      for (const event of cdp.events.slice(eventOffset)) {
        if (event.method !== "Runtime.consoleAPICalled") continue;
        const text = event.params.args[0]?.value;
        if (typeof text !== "string" || !text.startsWith("VALIDATION ")) continue;
        const value = JSON.parse(text.slice("VALIDATION ".length));
        if (value.name === "block-result") return value;
      }
      return null;
    }, ms + 15000);
    item.returnedMs = Date.now();
    assert.equal(item.block.heartbeatBefore, item.block.heartbeatAfter);
    assert(item.block.end.perfMs - item.block.start.perfMs >= ms, "Busy loop ended early");
    alive(chrome, "Chromium"); alive(recorder, "ffmpeg");
    // Baseline transition may only START after unblock: preserve its endpoint too.
    await sleep(ms * 0.8 + 600);
    item.after = await cdp.evaluate("validation.geometry()");
    assert(Math.abs(item.after.panelHeight - 264) < 1, "Final layout height milestone missing");
    assert(Math.abs(item.after.followerTop - item.before.followerTop - 240) < 1, "Normal-flow sibling did not move");
    if (kind === "queries") {
      for (const [index, panel] of item.after.panels.entries()) {
        assert(Math.abs(panel.panelHeight - 264) < 1, "Query panel final height missing");
        assert(Math.abs(panel.followerTop - item.before.panels[index].followerTop - 240) < 1, "Query sibling did not move");
      }
      assert(item.block.assertions.checks.every((check) => check.passed), "Immediate synchronous-query assertions failed (see block result)");
      assert.equal(item.block.scope?.windowScroll?.required, true, "Window-scroll coverage missing");
      const restoredAtMs = item.block.scope.windowScroll.restoredAtMs;
      assert(Number.isFinite(restoredAtMs) && restoredAtMs >= 0 && restoredAtMs < 250, "Window scroll not restored before guarded pixel sampling");
    }
    await screenshot(cdp, join(caseDir, "after-cdp.png"));
    alive(recorder, "ffmpeg");
    await stop(recorder, "SIGINT");
    assert([0, 255].includes(recorder.exitCode), `ffmpeg finalization failed: ${recorder.exitCode}/${recorder.signalCode}`);
    recorder = null;
    await traceStop(browser, caseDir);
    tracing = false;
    item.completed = true;
  } catch (error) {
    item.error = String(error.stack || error);
    run.failures.push(`${mode}/${name}: ${error.message}`);
  } finally {
    await stop(recorder, "SIGINT");
    if (tracing) {
      try { await traceStop(browser, caseDir); } catch (error) { item.traceError = String(error); }
    }
    item.finishedMs = Date.now();
    item.logEnd = statSync(chromeLog).size;
    writeFileSync(join(caseDir, "case.json"), JSON.stringify(item, null, 2));
    save();
  }
}

try {
  assert(existsSync(binary), `Missing binary ${binary}`);
  assert.equal(typeof WebSocket, "function", "Node 22+ built-in WebSocket required");
  for (const executable of ["Xvfb", "ffmpeg", "ffprobe", "python3", "xdotool"]) {
    assert.equal(spawnSync("which", [executable]).status, 0, `Missing ${executable}`);
  }
  const initialBuild = await buildSnapshot("initial");
  run.buildSha256 = initialBuild.sha256;
  run.binarySha256 = initialBuild.files.find((file) => file.name === basename(binary)).sha256;
  server = createServer((request, response) => {
    const name = new URL(request.url, "http://localhost").pathname;
    const files = { "/index.html": "text/html", "/a.html": "text/html", "/b.html": "text/html", "/unreplicable.html": "text/html", "/queries.html": "text/html", "/mem.html": "text/html", "/demo.js": "text/javascript", "/queries.js": "text/javascript", "/mem.js": "text/javascript", "/common.js": "text/javascript", "/demo.css": "text/css", "/queries.css": "text/css" };
    if (!files[name]) { response.writeHead(404); response.end(); return; }
    response.writeHead(200, { "Content-Type": files[name], "Cache-Control": "no-store" });
    const aliased = ["/a.html", "/b.html", "/unreplicable.html"].includes(name);
    const body = readFileSync(join(root, "demo", aliased ? "index.html" : name.slice(1)), "utf8");
    // The same demo plus one <img>: an element the replica cannot reproduce.
    response.end(name === "/unreplicable.html" ? body.replace("</aside>", `<img id="unreplicable" alt="" width="1" height="1" src="${UNREPLICABLE_IMAGE}"></aside>`) : body);
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  const base = `http://127.0.0.1:${server.address().port}`;
  const xlog = openSync(join(output, "xvfb.log"), "a");
  const xvfb = launch("Xvfb", ["-displayfd", "3", "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-noreset"], join(output, "xvfb.log"), { stdio: ["ignore", xlog, xlog, "pipe"] });
  closeSync(xlog);
  let displayNumber = "";
  xvfb.stdio[3].on("data", (data) => { displayNumber += data; });
  await waitFor(() => { alive(xvfb, "Xvfb"); return /^\d+\n/.test(displayNumber); });
  const display = `:${displayNumber.trim()}`;
  run.display = display;
  save();
  for (const mode of ["baseline", "omt"]) {
    const directory = join(output, mode);
    mkdirSync(directory);
    const profile = join(directory, "profile");
    mkdirSync(profile);
    const args = ["--no-sandbox", `--user-data-dir=${profile}`, "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--disable-dev-shm-usage", "--disable-hang-monitor", "--force-device-scale-factor=1", "--ozone-platform=x11", "--window-position=0,0", "--window-size=1280,800", "--enable-logging=stderr", "--v=0",
      mode === "omt" ? "--enable-blink-features=OffMainThreadRendering" : "--disable-blink-features=OffMainThreadRendering", "--app=about:blank"];
    const actualBuild = await buildSnapshot(mode);
    assert.equal(actualBuild.sha256, run.buildSha256, "Runtime build changed between flag-off and flag-on runs");
    const chrome = launch(binary, args, join(directory, "chrome.log"), { env: { ...process.env, DISPLAY: display, TZ: "UTC" } });
    try {
      const portFile = join(profile, "DevToolsActivePort");
      await waitFor(() => { alive(chrome, "Chromium"); return existsSync(portFile); }, 45000);
      const [port, browserPath] = readFileSync(portFile, "utf8").trim().split("\n");
      const browser = new CDP(`ws://127.0.0.1:${port}${browserPath}`, join(directory, "browser-cdp.jsonl"));
      sockets.push(browser);
      const version = await browser.call("Browser.getVersion");
      writeFileSync(join(directory, "version.json"), JSON.stringify({ ...version, args, binarySha256: run.binarySha256, buildSha256: actualBuild.sha256 }, null, 2));
      assert(version.product.endsWith(`/${expectedVersion}`), `Wrong binary version: ${version.product}`);
      const target = await waitFor(async () => {
        alive(chrome, "Chromium");
        const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(5000) });
        const targets = await response.json();
        return targets.find((item) => item.type === "page");
      });
      const cdp = new CDP(target.webSocketDebuggerUrl, join(directory, "page-cdp.jsonl"));
      sockets.push(cdp);
      await cdp.call("Runtime.enable");
      await cdp.call("Page.enable");
      await cdp.call("Inspector.enable");
      await browser.call("Target.setDiscoverTargets", { discover: true });
      for (const ms of [3000, 10000]) for (const kind of ["height", "grid", "queries"]) {
        await caseRun({ cdp, browser, chrome, base, mode, kind, ms, display, directory });
        alive(chrome, "Chromium");
        if (cdp.failure || browser.failure) throw cdp.failure || browser.failure;
      }
      const context = { cdp, browser, chrome, base, directory, display, root, port, mode, sockets, navigate, screenshot, externalScreenshot, traceStart, traceStop, waitFor };
      const checks = [["smoke", () => smoke(cdp, browser, target, base, directory, display)], ["native-input", nativeInput], ["page-threads", pageThreads], ["unreplicable", unreplicable], ["memory", memoryChurn]];
      for (const [name, check] of checks) {
        try { await check(context); } catch (error) { run.failures.push(`${mode}/${name}: ${error.stack || error}`); save(); }
        // Every stage navigates to a fresh fixture. An assertion failure remains
        // fatal to the report, but must not conceal independent stage failures.
        alive(chrome, "Chromium");
        if (cdp.failure || browser.failure) throw cdp.failure || browser.failure;
      }
      alive(chrome, "Chromium");
      if (cdp.failure || browser.failure) throw cdp.failure || browser.failure;
      cdp.close(); browser.close();
    } catch (error) { run.failures.push(`${mode}: ${error.stack || error}`); }
    finally {
      await stop(chrome);
      const log = readFileSync(join(directory, "chrome.log"), "utf8");
      const fatal = log.split("\n").filter((line) => /FATAL|Check failed|Received signal|AddressSanitizer|Segmentation fault|Trace\/breakpoint trap|GPU process exited unexpectedly|GPU process launch failed|Render process gone|Out of memory/i.test(line));
      writeFileSync(join(directory, "fatal-lines.json"), JSON.stringify(fatal, null, 2));
      if (fatal.length) run.failures.push(`${mode}: fatal Chromium log signatures`);
      save();
    }
  }
  assert.equal((await buildSnapshot("final")).sha256, run.buildSha256, "Runtime build changed during validation");
} catch (error) { run.failures.push(String(error.stack || error)); }
finally { await cleanup(); run.finishedMs = Date.now(); save(); }

const analysis = spawnSync("python3", [join(root, "analyze.py"), output], { stdio: "inherit", timeout: 300000 });
if (analysis.error) run.failures.push(String(analysis.error));
save();
console.log(`Results retained: ${output}`);
process.exitCode = run.failures.length || analysis.status !== 0 ? 1 : 0;
