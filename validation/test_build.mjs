import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fingerprintBuild } from "./build.mjs";

function fixture(t) {
  const directory = mkdtempSync(join(tmpdir(), "omt-build-"));
  t.after(() => rmSync(directory, { recursive: true }));
  const binary = join(directory, "chrome");
  writeFileSync(binary, "browser executable");
  return { directory, binary };
}

test("component change is detected with unchanged executable", async (t) => {
  const { directory, binary } = fixture(t);
  const component = join(directory, "libblink_core.so");
  writeFileSync(component, "old library");
  const before = await fingerprintBuild(binary);
  writeFileSync(component, "new library");
  const after = await fingerprintBuild(binary);
  assert.notEqual(after.sha256, before.sha256);
  assert.deepEqual(after.files[0], before.files[0]);
});

test("runtime resources are included but build debris is excluded", async (t) => {
  const { directory, binary } = fixture(t);
  mkdirSync(join(directory, "locales"));
  for (const name of ["libfoo.so.1", "icudtl.dat", "resources.pak", "snapshot.bin", "chrome_crashpad_handler", "locales/en-GB.pak", "build.ninja", "scratch.o"]) writeFileSync(join(directory, name), name);
  const manifest = await fingerprintBuild(binary);
  assert.deepEqual(manifest.files.map((file) => file.name), ["chrome", "chrome_crashpad_handler", "icudtl.dat", "libfoo.so.1", "locales/en-GB.pak", "resources.pak", "snapshot.bin"]);
  writeFileSync(join(directory, "scratch.o"), "different object");
  assert.deepEqual(await fingerprintBuild(binary), manifest);
});

test("added or removed library changes the manifest", async (t) => {
  const { directory, binary } = fixture(t);
  const before = await fingerprintBuild(binary);
  writeFileSync(join(directory, "libextra.so"), "extra");
  assert.notEqual((await fingerprintBuild(binary)).sha256, before.sha256);
  rmSync(join(directory, "libextra.so"));
  assert.deepEqual(await fingerprintBuild(binary), before);
});
