// Real X display (e.g. the RTX 4090 Xorg :20) helpers. Pure parsers are unit
// tested; nothing here starts or restarts X, KWin or any service.

// `xdotool ... --shell` output: KEY=VALUE lines.
export function parseShell(text) {
  return Object.fromEntries(text.trim().split("\n").map((line) => {
    const [name, value] = line.split("=");
    return [name, Number(value)];
  }));
}

// `xset q` DPMS section. "Monitor is" is only printed while DPMS is enabled.
export function parseDpms(text) {
  const enabled = /DPMS is (Enabled|Disabled)/.exec(text)?.[1];
  const monitor = /Monitor is (On|Off|Standby|Suspend|in \w+)/.exec(text)?.[1] ?? null;
  if (!enabled || (enabled === "Enabled" && !monitor)) throw new Error(`xset q has no DPMS state: ${text.slice(-200)}`);
  return { enabled: enabled === "Enabled", monitor };
}

// Restore exactly the pre-run state (force the monitor state last).
export function dpmsRestoreCommands(before) {
  const commands = [[before.enabled ? "+dpms" : "-dpms"]];
  if (before.enabled && before.monitor !== "On") commands.push(["dpms", "force", before.monitor.replace(/^in /, "").toLowerCase()]);
  return commands;
}

// x11grab input for a capture region's top-left.
export function grabInput(display, origin) {
  return origin ? `${display}+${origin.x},${origin.y}` : display;
}

// `nvidia-smi` process table: "|  0  N/A  N/A  <pid>  <type>  <name>  <n>MiB |".
export function vramMib(table, pid) {
  for (const line of table.split("\n")) {
    const match = /^\|\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+.*?\s(\d+)MiB\s*\|$/.exec(line);
    if (match && Number(match[1]) === pid) return Number(match[2]);
  }
  return null;
}
