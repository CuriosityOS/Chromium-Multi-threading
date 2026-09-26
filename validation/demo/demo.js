"use strict";

const panel = document.getElementById("panel");
const status = document.getElementById("status");
const params = new URLSearchParams(location.search);
const kind = params.get("kind") || "height";
const milliseconds = Number(params.get("ms") || 3000);
let heartbeat = 0;
let running = false;
const smokeStyle = document.createElement("style");
document.head.append(smokeStyle);
const smokeSheet = smokeStyle.sheet;

function configure(nextKind, ms) {
  if (!["height", "grid"].includes(nextKind) || ![3000, 10000].includes(ms)) {
    throw new Error("Unsupported test case");
  }
  panel.className = nextKind;
  panel.style.setProperty("--duration", `${ms * 0.8}ms`);
  document.getElementById("case-label").textContent = `${nextKind} · ${ms / 1000}s block`;
}

function runBlock(ms) {
  if (running) throw new Error("Block already running");
  running = true;
  const beforeHeartbeat = heartbeat;
  // CRITICAL: toggle and busy loop are in this ONE synchronous task.
  // No rAF, timeout, await, computed style or layout read after the toggle.
  panel.classList.toggle("open");
  performance.mark("validation:mutation");
  const start = milestone("block-start", { ms, heartbeat: beforeHeartbeat });
  const until = performance.now() + ms;
  let spins = 0;
  while (performance.now() < until) spins++;
  const end = milestone("block-end", { heartbeat, spins });
  performance.measure("validation:busy", "validation:block-start", "validation:block-end");
  const result = {
    ms,
    kind: panel.classList.contains("grid") ? "grid" : "height",
    start,
    end,
    heartbeatBefore: beforeHeartbeat,
    heartbeatAfter: heartbeat,
  };
  if (heartbeat !== beforeHeartbeat) throw new Error("JS heartbeat ran inside synchronous block");
  status.textContent = `Finished ${ms / 1000}s block. Inspect external capture; no frame-count claim.`;
  milestone("block-result", result);
  window.lastBlock = result;
  running = false;
  return result;
}

function smoke(step) {
  const slot = document.getElementById("insert-slot");
  const text = document.getElementById("text-probe");
  const inline = document.getElementById("style-probe");
  const cssom = document.getElementById("cssom-probe");
  switch (step) {
    case "insert": {
      const child = document.createElement("div");
      child.id = "inserted";
      child.textContent = "Inserted node";
      child.style.backgroundColor = "rgb(220, 60, 140)";
      slot.append(child);
      break;
    }
    case "remove":
      document.getElementById("inserted").remove();
      break;
    case "text":
      text.textContent = "AFTER: text mutation";
      break;
    case "inline":
      inline.style.backgroundColor = "rgb(40, 200, 80)";
      inline.style.height = "45px";
      break;
    case "cssom-insert":
      smokeSheet.insertRule("#cssom-probe { background-color: rgb(130, 80, 220); height: 45px; }", 0);
      break;
    case "cssom-delete":
      smokeSheet.deleteRule(0);
      break;
    default:
      throw new Error(`Unknown smoke step: ${step}`);
  }
  const target = step === "insert" || step === "remove" ? slot : step === "text" ? text : step === "inline" ? inline : cssom;
  const rect = target.getBoundingClientRect();
  return milestone(`smoke-${step}`, {
    rect: { x: Math.floor(rect.x), y: Math.floor(rect.y), width: 230, height: 45 },
    inserted: Boolean(document.getElementById("inserted")),
    text: text.textContent,
    inlineColor: getComputedStyle(inline).backgroundColor,
    inlineHeight: inline.getBoundingClientRect().height,
    cssomColor: getComputedStyle(cssom).backgroundColor,
    ruleCount: smokeSheet.cssRules.length,
  });
}

window.validation = {
  runBlock,
  smoke,
  geometry() {
    const rect = document.getElementById("proof").getBoundingClientRect();
    return {
      proof: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      panelHeight: panel.getBoundingClientRect().height,
      followerTop: document.getElementById("follower").getBoundingClientRect().top,
      width: innerWidth,
      height: innerHeight,
      dpr: devicePixelRatio,
    };
  },
};

setInterval(() => {
  document.getElementById("heartbeat").textContent = String(++heartbeat);
}, 100);
addEventListener("resize", () => milestone("resize", { width: innerWidth, height: innerHeight }));
for (const button of document.querySelectorAll("button")) {
  button.addEventListener("click", () => {
    configure(button.dataset.kind, Number(button.dataset.ms));
    status.textContent = "Armed: block begins in 1 second.";
    // Settle only the BEFORE state. The later runBlock itself never yields.
    setTimeout(() => runBlock(Number(button.dataset.ms)), 1000);
  });
}
configure(kind, milliseconds);
status.textContent = `${params.get("mode") || "manual"}: ready`;
window.validationReady = true;
milestone("ready", { kind, ms: milliseconds });
