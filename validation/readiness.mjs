// Console history is replayed when a BFCache document's Runtime agent restores.
// Filter by occurrence time, never merely by delivery order / event-array offset.
export function findMilestone(events, { from = 0, name, notBeforeMs, accept = () => true }) {
  for (const event of events.slice(from)) {
    if (event.method !== "Runtime.consoleAPICalled") continue;
    const text = event.params.args[0]?.value;
    if (typeof text !== "string" || !text.startsWith("VALIDATION ")) continue;
    const value = JSON.parse(text.slice("VALIDATION ".length));
    if (value?.name === name && Number.isFinite(value.epochMs) && value.epochMs >= notBeforeMs && accept(value)) return value;
  }
  return null;
}

export async function waitForResize(cdp, waitFor, before, from, notBeforeMs, onSample = () => {}) {
  return waitFor(async () => {
    const geometry = await cdp.evaluate("validation.geometry()");
    const milestone = findMilestone(cdp.events, {
      from, name: "resize", notBeforeMs,
      accept: (value) => value.width === geometry.width && value.height === geometry.height,
    });
    onSample({ observedMs: Date.now(), geometry, milestone });
    return geometry.width !== before.width && geometry.height !== before.height && milestone ? { geometry, milestone } : null;
  });
}
