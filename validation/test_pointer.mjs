import assert from "node:assert/strict";
import test from "node:test";
import { movePointer } from "./extended.mjs";

function driver(before, after) {
  const commands = [];
  let reads = 0;
  const xdo = (args) => {
    commands.push(args);
    if (args[0] === "getmouselocation") return reads++ === 0 ? before : after;
    return "";
  };
  return { xdo, commands };
}

for (const initial of ["X=10\nY=20\nSCREEN=0", "X=786\nY=785\nSCREEN=0"]) {
  test(`pointer readback, initial ${initial.replaceAll("\n", " ")}`, () => {
    const { xdo, commands } = driver(initial, "X=786\nY=785\nSCREEN=0");
    const result = movePointer(xdo, 786, 785);
    assert.equal(result.after.X, 786);
    assert.equal(result.after.Y, 785);
    assert.deepEqual(commands, [["getmouselocation", "--shell"], ["mousemove", "786", "785"], ["getmouselocation", "--shell"]]);
  });
}

test("incorrect pointer destination fails before any click", () => {
  const { xdo, commands } = driver("X=10\nY=20", "X=785\nY=785");
  assert.throws(() => movePointer(xdo, 786, 785), /intended X/);
  assert(!commands.some((args) => args[0] === "mousedown"));
});

test("missing pointer coordinates fail closed", () => {
  const { xdo } = driver("WINDOW=1", "X=786\nY=785");
  assert.throws(() => movePointer(xdo, 786, 785), /Invalid pointer location/);
});
