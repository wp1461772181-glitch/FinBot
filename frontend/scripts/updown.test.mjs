import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_UPDOWN, UPDOWN_KEY, UPDOWNS, applyUpdown, saveUpdown, storedUpdown } from "../src/updown.mjs";

const memory = () => { const data = new Map(); return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v) }; };

test("the market colours default to green up and read back what was saved", () => {
  const storage = memory();
  assert.equal(DEFAULT_UPDOWN, "green-up");
  assert.equal(storedUpdown(storage), "green-up");
  assert.equal(saveUpdown("red-up", storage), "red-up");
  assert.equal(storage.data.get(UPDOWN_KEY), "red-up");
  assert.equal(storedUpdown(storage), "red-up");
  assert.equal(saveUpdown("green-up", storage), "green-up");
  assert.equal(storedUpdown(storage), "green-up");
});

test("an unknown value is never saved or applied; the stored choice stays", () => {
  const storage = memory();
  saveUpdown("red-up", storage);
  assert.equal(saveUpdown("blue-up", storage), "red-up");
  assert.equal(storage.data.get(UPDOWN_KEY), "red-up");
  storage.data.set(UPDOWN_KEY, "garbage");
  assert.equal(storedUpdown(storage), "green-up");
  const root = { dataset: {} };
  assert.equal(applyUpdown("sideways", root), "green-up");
  assert.equal(root.dataset.updown, "green-up");
});

test("applying writes data-updown on the root, for both choices", () => {
  const root = { dataset: {} };
  for (const choice of UPDOWNS) {
    assert.equal(applyUpdown(choice, root), choice);
    assert.equal(root.dataset.updown, choice);
  }
});

test("storage that throws falls back to the default and does not throw on save", () => {
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.equal(storedUpdown(broken), "green-up");
  assert.equal(saveUpdown("red-up", broken), "red-up");
  assert.equal(applyUpdown("red-up", undefined), "red-up");
});
