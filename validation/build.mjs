import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createReadStream, existsSync, readdirSync, statSync } from "node:fs";
import { basename, dirname, join } from "node:path";

async function fingerprintFile(path) {
  const before = statSync(path);
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  const after = statSync(path);
  assert(before.ino === after.ino && before.size === after.size && before.mtimeMs === after.mtimeMs,
    `Runtime file changed while hashing: ${path}`);
  return { size: after.size, sha256: hash.digest("hex") };
}

export async function fingerprintBuild(binary) {
  const directory = dirname(binary);
  const names = new Set([basename(binary)]);
  for (const name of readdirSync(directory)) {
    if (/\.(so(?:\.\d+)*|pak|bin|dat)$/.test(name) || name === "chrome_crashpad_handler") names.add(name);
  }
  const locales = join(directory, "locales");
  if (existsSync(locales)) {
    for (const name of readdirSync(locales)) if (name.endsWith(".pak")) names.add(`locales/${name}`);
  }
  const files = [];
  for (const name of [...names].sort()) files.push({ name, ...await fingerprintFile(join(directory, name)) });
  return { sha256: createHash("sha256").update(JSON.stringify(files)).digest("hex"), files };
}
