#!/usr/bin/env node
// Xvfb/FFmpeg transport self-test. NEVER starts Chromium.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { closeSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { captureArgs } from "./media.mjs";
import { movePointer } from "./extended.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const directory = join(root, "preflight", `capture-${Date.now()}`);
mkdirSync(directory, { recursive: true });
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const xlog = openSync(join(directory, "xvfb.log"), "w");
const xvfb = spawn("Xvfb", ["-displayfd", "3", "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-noreset"], { stdio: ["ignore", xlog, xlog, "pipe"] });
closeSync(xlog);
let recorder;
let number = "";
let spawnError;
xvfb.on("error", (error) => { spawnError = error; });
xvfb.stdio[3].on("data", (data) => { number += data; });
async function stop(child, signal) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill(signal);
  const deadline = Date.now() + 5000;
  while (child.exitCode === null && child.signalCode === null && Date.now() < deadline) await sleep(25);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}
try {
  const deadline = Date.now() + 10000;
  while (!/^\d+\n/.test(number)) {
    if (spawnError) throw spawnError;
    assert(xvfb.exitCode === null && Date.now() < deadline, "Xvfb failed readiness");
    await sleep(25);
  }
  const xdo = (args) => {
    const input = spawnSync("xdotool", args, { env: { ...process.env, DISPLAY: `:${number.trim()}` }, encoding: "utf8", timeout: 10000 });
    assert.equal(input.status, 0, input.error?.message || input.stderr);
    return input.stdout.trim();
  };
  const pointerReadbacks = [movePointer(xdo, 1200, 750), movePointer(xdo, 1200, 750)];
  const startedMs = Date.now();
  const video = join(directory, "capture.mkv");
  const log = openSync(join(directory, "ffmpeg.log"), "w");
  const args = captureArgs(`:${number.trim()}`, video, join(directory, "progress.log"));
  recorder = spawn("ffmpeg", args, { stdio: ["ignore", log, log] });
  recorder.on("error", (error) => { spawnError = error; });
  closeSync(log);
  await sleep(2200);
  if (spawnError) throw spawnError;
  assert.equal(recorder.exitCode, null, "ffmpeg exited before capture completed");
  await stop(recorder, "SIGINT");
  assert([0, 255].includes(recorder.exitCode), "ffmpeg could not finalize capture");
  const probe = spawnSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", video], { encoding: "utf8", timeout: 10000 });
  assert.equal(probe.status, 0, probe.stderr);
  const pts = JSON.parse(probe.stdout).frames.map((frame) => Number(frame.best_effort_timestamp_time) * 1000);
  assert(pts.length >= 30, "Insufficient capture frames");
  assert(Math.abs(pts[0] - startedMs) < 1000, "FFmpeg PTS must remain absolute epoch milliseconds");
  assert(pts.every((value, i) => i === 0 || value > pts[i - 1]), "PTS not strictly increasing");
  const result = { passed: true, chromiumLaunched: false, xtestMouseVerified: true, pointerReadbacks, startedMs, firstPtsMs: pts[0], lastPtsMs: pts.at(-1), capturedFrames: pts.length, args };
  writeFileSync(join(directory, "result.json"), JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result, null, 2));
  console.log(`Capture self-test retained: ${directory}`);
} catch (error) {
  writeFileSync(join(directory, "failure.txt"), String(error.stack || error));
  throw error;
} finally {
  await stop(recorder, "SIGINT");
  await stop(xvfb, "SIGTERM");
}
