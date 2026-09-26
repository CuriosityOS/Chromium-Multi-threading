"use strict";

function milestone(name, data = {}) {
  performance.mark(`validation:${name}`);
  const entry = { name, epochMs: Date.now(), perfMs: performance.now(), ...data };
  console.log(`VALIDATION ${JSON.stringify(entry)}`);
  return entry;
}

// pageshow fires for initial loads and BFCache restores; load need not re-fire.
window.addEventListener("pageshow", (event) => {
  milestone("pageshow", { persisted: event.persisted, url: location.href });
});
