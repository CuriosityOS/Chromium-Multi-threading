"use strict";

// Churn in short 16ms timer tasks only (never a long task): list replacement,
// transition class toggle, style element insert/remove and a layout read.
const churnList = document.getElementById("churn-list");
const churnPanel = document.getElementById("panel");
let churnTicks = 0;

function churnOnce() {
  churnTicks++;
  churnList.innerHTML = Array.from({ length: 300 }, (_, index) => `<li>item ${churnTicks}-${index}</li>`).join("");
  churnPanel.classList.toggle("open");
  const style = document.createElement("style");
  style.textContent = `#churn-list li:nth-child(${(churnTicks % 300) + 1}) { color: rgb(${churnTicks % 256}, 120, 200); }`;
  document.head.append(style);
  style.remove();
  return churnPanel.offsetHeight;
}

function startChurn(ms) {
  const start = milestone("churn-start", { ms });
  const timer = setInterval(() => {
    if (performance.now() - start.perfMs >= ms) {
      clearInterval(timer);
      document.getElementById("status").textContent = "Idle";
      milestone("churn-end", { ticks: churnTicks });
      return;
    }
    churnOnce();
  }, 16);
  document.getElementById("status").textContent = "Churning";
  return start;
}

window.validation = { startChurn };
window.validationReady = true;
milestone("ready", { kind: "mem" });
