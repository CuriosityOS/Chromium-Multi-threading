"use strict";

const queryParams = new URLSearchParams(location.search);
const queryMs = Number(queryParams.get("ms") || 3000);
if (![3000, 10000].includes(queryMs)) throw new Error("Invalid query block duration");
const queryPanels = [document.getElementById("height-panel"), document.getElementById("grid-panel")];
for (const element of queryPanels) element.style.setProperty("--duration", `${queryMs * 0.8}ms`);
const queryContainer = document.getElementById("query-container");
const queryStyle = document.createElement("style");
document.head.append(queryStyle);
const shadowHost = document.getElementById("shadow-host");
const shadow = shadowHost.attachShadow({ mode: "open" });
shadow.innerHTML = '<div id="shadow-inner" style="position:absolute;left:0;top:0;width:80px;height:40px;background:#a080d0">Shadow</div>';
let queryHeartbeat = 0;
setInterval(() => { document.getElementById("heartbeat").textContent = String(++queryHeartbeat); }, 100);
const inputEvents = [];
for (const type of ["mousedown", "mouseup", "click"]) {
  document.addEventListener(type, (event) => {
    inputEvents.push({ type, target: event.target.id, offsetX: event.offsetX, offsetY: event.offsetY, clientX: event.clientX, clientY: event.clientY, isTrusted: event.isTrusted, button: event.button });
    milestone("input", inputEvents.at(-1));
  });
}

function mutationQueries(viewport, blockStart) {
  const checks = [];
  const check = (name, actual, expected) => checks.push({ name, actual, expected, passed: actual === expected });
  const box = document.createElement("div");
  box.id = "geometry-probe";
  box.style.cssText = "position:absolute;left:11px;top:13px;box-sizing:content-box;width:123px;height:40px;padding:5px;border:2px solid;margin:0;--test-token:19px";
  queryContainer.append(box);
  check("offsetWidth", box.offsetWidth, 137);
  check("offsetHeight", box.offsetHeight, 54);
  check("offsetLeft", box.offsetLeft, 11);
  check("offsetTop", box.offsetTop, 13);
  check("offsetParent identity", box.offsetParent === queryContainer, true);
  check("clientWidth", box.clientWidth, 133);
  check("clientHeight", box.clientHeight, 50);
  check("clientLeft", box.clientLeft, 2);
  check("clientTop", box.clientTop, 2);
  const rect = box.getBoundingClientRect();
  check("rect width", rect.width, 137);
  check("rect height", rect.height, 54);
  check("rect x", rect.x, 35);
  check("rect y", rect.y, 623);
  const rects = box.getClientRects();
  check("client rect count", rects.length, 1);
  check("client rect width", rects[0]?.width, 137);
  const range = document.createRange();
  range.selectNode(box);
  const rangeRects = range.getClientRects();
  const rangeBounds = range.getBoundingClientRect();
  check("Range client rect count", rangeRects.length, 1);
  check("Range client rect width", rangeRects[0]?.width, 137);
  check("Range client rect height", rangeRects[0]?.height, 54);
  check("Range bounding width", rangeBounds.width, 137);
  check("Range bounding height", rangeBounds.height, 54);
  check("Range bounding x", rangeBounds.x, 35);
  check("Range bounding y", rangeBounds.y, 623);
  check("computed width property", getComputedStyle(box).width, "123px");
  check("computed width getPropertyValue", getComputedStyle(box).getPropertyValue("width"), "123px");
  check("computed custom property", getComputedStyle(box).getPropertyValue("--test-token").trim(), "19px");
  box.style.width = "143px";
  check("immediate inline mutation offsetWidth", box.offsetWidth, 157);
  box.style.width = "";
  queryStyle.sheet.insertRule("#geometry-probe { width: 123px; --test-token: 23px; }", 0);
  check("CSSOM insertRule geometry", box.offsetWidth, 137);
  box.style.removeProperty("--test-token");
  check("CSSOM custom property", getComputedStyle(box).getPropertyValue("--test-token").trim(), "23px");
  queryStyle.sheet.insertRule('#geometry-probe::before { content: ""; display:block; width:17px; height:3px; --pseudo-token:7px; }', 1);
  check("pseudo computed width", getComputedStyle(box, "::before").width, "17px");
  check("pseudo property value", getComputedStyle(box, "::before").getPropertyValue("height"), "3px");
  check("pseudo custom property", getComputedStyle(box, "::before").getPropertyValue("--pseudo-token").trim(), "7px");
  queryStyle.sheet.deleteRule(1);
  queryStyle.sheet.deleteRule(0);
  box.style.width = "123px";
  check("CSSOM deleteRule", queryStyle.sheet.cssRules.length, 0);
  box.remove();
  check("removed offsetWidth", box.offsetWidth, 0);
  check("removed rects", box.getClientRects().length, 0);
  check("removed offsetParent", box.offsetParent, null);
  queryContainer.append(box);
  check("reinserted geometry", box.offsetWidth, 137);
  const text = document.getElementById("query-text");
  text.innerHTML = 'Visible<span style="display:none">Hidden</span>';
  check("innerText excludes display:none", text.innerText, "Visible");
  text.textContent = "Changed text";
  check("text mutation innerText", text.innerText, "Changed text");
  const scroll = document.getElementById("scroll-probe");
  scroll.scrollLeft = 17;
  scroll.scrollTop = 23;
  check("scrollLeft", scroll.scrollLeft, 17);
  check("scrollTop", scroll.scrollTop, 23);
  check("scrollWidth", scroll.scrollWidth, 220);
  check("scrollHeight", scroll.scrollHeight, 180);
  check("scroll clientWidth", scroll.clientWidth, 100);
  check("scroll clientHeight", scroll.clientHeight, 60);
  // CSS guarantees vertical overflow. Numeric scrollTo uses the explicit auto
  // scroll behavior; restore in this same task before guarded visual sampling.
  check("window innerWidth", window.innerWidth, viewport.width);
  check("window innerHeight", window.innerHeight, viewport.height);
  check("window initial scrollX", window.scrollX, 0);
  check("window initial scrollY", window.scrollY, 0);
  const unscrolledTop = box.getBoundingClientRect().top;
  window.scrollTo(0, 40);
  check("window scrollX after scrollTo", window.scrollX, 0);
  check("window scrollY after scrollTo", window.scrollY, 40);
  check("window scroll moves rect top", box.getBoundingClientRect().top - unscrolledTop, -40);
  window.scrollTo(0, 0);
  check("window restored scrollX", window.scrollX, 0);
  check("window restored scrollY", window.scrollY, 0);
  check("window restored rect top", box.getBoundingClientRect().top, unscrolledTop);
  const restoredAtMs = performance.now() - blockStart;
  performance.mark("validation:window-scroll-restored");
  check("document light hit", document.elementFromPoint(434, 630)?.id, "hit-probe");
  check("document light hit stack", document.elementsFromPoint(434, 630)[0]?.id, "hit-probe");
  check("document shadow retarget", document.elementFromPoint(534, 630)?.id, "shadow-host");
  const documentShadowStack = document.elementsFromPoint(534, 630);
  check("document excludes shadow internals", documentShadowStack.some((element) => element.id === "shadow-inner"), false);
  check("document shadow stack host", documentShadowStack[0]?.id, "shadow-host");
  check("shadow elementFromPoint", shadow.elementFromPoint(534, 630)?.id, "shadow-inner");
  check("shadow elementsFromPoint", shadow.elementsFromPoint(534, 630)[0]?.id, "shadow-inner");
  check("document outside viewport", document.elementFromPoint(-1, -1), null);
  check("document outside viewport stack", document.elementsFromPoint(-1, -1).length, 0);
  check("shadow outside viewport", shadow.elementFromPoint(-1, -1), null);
  check("shadow outside viewport stack", shadow.elementsFromPoint(-1, -1).length, 0);
  // Out-of-root semantics are retained for baseline comparison rather than invented expectations.
  const outsideShadow = { element: shadow.elementFromPoint(434, 630)?.id ?? null, elements: shadow.elementsFromPoint(434, 630).map((element) => element.id || element.tagName) };
  const focus = document.getElementById("input-button");
  focus.focus({ preventScroll: true });
  check("enabled button focusable", document.activeElement === focus, true);
  document.getElementById("disabled-button").focus({ preventScroll: true });
  check("disabled button not focusable", document.activeElement === focus, true);
  document.getElementById("hidden-button").focus({ preventScroll: true });
  check("hidden button not focusable", document.activeElement === focus, true);
  focus.blur();
  // Window scrolling is now required coverage. Bulk computed-style getters
  // remain excluded; recording that boundary does not invoke unsupported APIs.
  const scope = {
    windowScroll: { required: true, restoredAtMs, focusPreventsScroll: true },
    computedStyleEnumeration: { required: false, excludedMembers: ["cssText", "length"], accessPattern: "named properties and getPropertyValue only" },
  };
  return { checks, outsideShadow, scope };
}

function querySample(start) {
  const queryBeginMs = performance.now();
  const values = queryPanels.map((element) => ({ offset: element.offsetHeight, rect: element.getBoundingClientRect().height, computed: Number.parseFloat(getComputedStyle(element).height) }));
  return { t: queryBeginMs - start, queryBeginMs, queryEndMs: performance.now(), height: values[0], grid: values[1] };
}

function runQueryBlock(ms, viewport) {
  if (!viewport || !Number.isFinite(viewport.width) || !Number.isFinite(viewport.height)) throw new Error("Missing pre-block viewport measurements");
  const beforeHeartbeat = queryHeartbeat;
  // Both mutations and every query below stay inside ONE ordinary timer task.
  queryPanels[0].classList.toggle("open");
  queryPanels[1].classList.toggle("open");
  performance.mark("validation:mutation");
  const start = milestone("block-start", { ms, heartbeat: beforeHeartbeat });
  const { scope, ...assertions } = mutationQueries(viewport, start.perfMs);
  const samples = [];
  const deadline = start.perfMs + ms;
  let next = performance.now();
  while (performance.now() < deadline) {
    if (performance.now() >= next) {
      samples.push(querySample(start.perfMs));
      next = performance.now() + 200;
    }
  }
  samples.push(querySample(start.perfMs));
  const end = milestone("block-end", { heartbeat: queryHeartbeat });
  performance.measure("validation:busy", "validation:block-start", "validation:block-end");
  const result = { ms, kind: "queries", start, end, heartbeatBefore: beforeHeartbeat, heartbeatAfter: queryHeartbeat, assertions, samples, scope };
  milestone("block-result", result);
  document.getElementById("status").textContent = `Completed ${ms / 1000}s query block; inspect external evidence.`;
  return result;
}

window.validation = {
  runBlock: runQueryBlock,
  inputEvents,
  inputGeometry() {
    const button = document.getElementById("input-button");
    const rect = button.getBoundingClientRect();
    return { x: rect.x + button.clientLeft + 20, y: rect.y + button.clientTop + 15, expectedOffsetX: 20, expectedOffsetY: 15 };
  },
  geometry() {
    const elements = queryPanels.map((element) => ({ panelHeight: element.getBoundingClientRect().height, followerTop: element.nextElementSibling.getBoundingClientRect().top }));
    return { ...elements[0], panels: elements, dpr: devicePixelRatio, width: innerWidth, height: innerHeight };
  },
};
window.validationReady = true;
milestone("ready", { kind: "queries", ms: queryMs });
