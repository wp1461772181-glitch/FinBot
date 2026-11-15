import assert from "node:assert/strict";
import test from "node:test";
import { SPLIT, readTags } from "../src/tag-input.mjs";
import { MAX_FOCUS_COMPANIES, parseFocusSymbols } from "../src/bot-items.mjs";

const focus = { normalize: (raw) => raw.trim().toUpperCase(), validate: (item) => parseFocusSymbols(item).companies.length === 1, max: MAX_FOCUS_COMPANIES };

test("a typed text is split on spaces, commas (also the full-width ones) and semicolons", () => {
  assert.deepEqual(readTags("aapl, msft，nvda、tsla;goog；meta  brk.b", [], focus).add, ["AAPL", "MSFT", "NVDA", "TSLA", "GOOG", "META", "BRK.B"]);
  assert.ok(SPLIT.test("a b") && SPLIT.test("a,b") && !SPLIT.test("ab"));
});

test("an item that is not a ticker is refused, as typed, and the valid ones of the same text still go in", () => {
  const read = readTags("AAPL, XYZ1, msft, 苹果", [], focus);
  assert.deepEqual(read.add, ["AAPL", "MSFT"]);
  assert.deepEqual(read.invalid, ["XYZ1", "苹果"]);
  assert.equal(read.cut, false);
});

test("an item already in the list, or twice in the text, is not added again", () => {
  assert.deepEqual(readTags("AAPL msft MSFT", ["AAPL"], focus), { add: ["MSFT"], invalid: [], cut: false });
});

test("the limit cuts the rest and says so; nothing is refused for it", () => {
  const have = Array.from({ length: 19 }, (_, i) => `A${String.fromCharCode(65 + i)}`);
  const read = readTags("ZA ZB ZC", have, focus);
  assert.deepEqual(read, { add: ["ZA"], invalid: [], cut: true });
});

test("empty and blank texts add nothing", () => {
  assert.deepEqual(readTags("", [], focus), { add: [], invalid: [], cut: false });
  assert.deepEqual(readTags("  ,, ; ", [], focus), { add: [], invalid: [], cut: false });
  assert.deepEqual(readTags(undefined, [], focus), { add: [], invalid: [], cut: false });
});
