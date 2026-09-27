// Real-display option helpers. Pure; never touches an X server.
import assert from "node:assert/strict";
import { test } from "node:test";
import { dpmsRestoreCommands, grabInput, parseDpms, parseShell, vramMib } from "./display.mjs";
import { captureArgs } from "./media.mjs";

const xsetQ = (state, monitor) => `Screen Saver:\n  timeout:  0    cycle:  600\nDPMS (Display Power Management Signaling):\n  Standby: 0    Suspend: 0    Off: 0\n  DPMS is ${state}\n  Monitor is ${monitor}\n`;

test("parseDpms reads xset q", () => {
  assert.deepEqual(parseDpms(xsetQ("Enabled", "Off")), { enabled: true, monitor: "Off" });
  assert.deepEqual(parseDpms(xsetQ("Disabled", "On")), { enabled: false, monitor: "On" });
  assert.deepEqual(parseDpms("  DPMS is Disabled\n"), { enabled: false, monitor: null });
  assert.throws(() => parseDpms("  DPMS is Enabled\n"), /no DPMS state/);
  assert.throws(() => parseDpms("Screen Saver:\n"), /no DPMS state/);
});

test("DPMS restore returns exactly the prior state", () => {
  assert.deepEqual(dpmsRestoreCommands({ enabled: true, monitor: "Off" }), [["+dpms"], ["dpms", "force", "off"]]);
  assert.deepEqual(dpmsRestoreCommands({ enabled: false, monitor: "On" }), [["-dpms"]]);
  assert.deepEqual(dpmsRestoreCommands({ enabled: false, monitor: null }), [["-dpms"]]);
  assert.deepEqual(dpmsRestoreCommands({ enabled: true, monitor: "in Standby" }), [["+dpms"], ["dpms", "force", "standby"]]);
});

test("capture input and window geometry", () => {
  assert.equal(grabInput(":99", null), ":99");
  assert.equal(grabInput(":20", { x: 0, y: 52 }), ":20+0,52");
  assert.deepEqual(parseShell("WINDOW=2097156\nX=0\nY=52\nWIDTH=1280\nHEIGHT=800\nSCREEN=0\n"), { WINDOW: 2097156, X: 0, Y: 52, WIDTH: 1280, HEIGHT: 800, SCREEN: 0 });
});

test("capture framerate is opt-in and Xvfb default stays 30", () => {
  const rate = (args) => args[args.indexOf("-framerate") + 1];
  assert.equal(rate(captureArgs(":99", "v.mkv", "p.log")), "30");
  const gpu = captureArgs(":20+0,52", "v.mkv", "p.log", 60);
  assert.equal(rate(gpu), "60");
  assert.equal(gpu[gpu.indexOf("-i") + 1], ":20+0,52");
});

test("vramMib parses the nvidia-smi process table", () => {
  const table = [
    "|    0   N/A  N/A          259518      G   /usr/lib/xorg/Xorg                      283MiB |",
    "|    0   N/A  N/A         3211771      G   ...ess-type=gpu-process --no-sandbox      57MiB |",
  ].join("\n");
  assert.equal(vramMib(table, 3211771), 57);
  assert.equal(vramMib(table, 259518), 283);
  assert.equal(vramMib(table, 1), null);
});
