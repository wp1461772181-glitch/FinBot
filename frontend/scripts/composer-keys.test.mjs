import test from "node:test";
import assert from "node:assert/strict";
import { composerKeyAction, isImeKey } from "../src/composer-keys.mjs";

const closed = { composing: false, menuCount: 0 };
const open = { composing: false, menuCount: 3 };
const key = (k, extra = {}) => ({ key: k, shiftKey: false, isComposing: false, keyCode: k === "Enter" ? 13 : 0, ...extra });

test("Enter sends, Shift+Enter breaks the line", () => {
  assert.equal(composerKeyAction(key("Enter"), closed), "send");
  assert.equal(composerKeyAction(key("Enter", { shiftKey: true }), closed), "none");
});

test("Enter that belongs to an input method never sends: composing flag, isComposing, or Safari's keyCode 229", () => {
  assert.equal(composerKeyAction(key("Enter"), { composing: true, menuCount: 0 }), "none");
  assert.equal(composerKeyAction(key("Enter", { isComposing: true }), closed), "none");
  assert.equal(composerKeyAction(key("Enter", { keyCode: 229 }), closed), "none");
});

test("after the composition ends, Enter sends again", () => {
  assert.equal(composerKeyAction(key("Enter"), { composing: false, menuCount: 0 }), "send");
});

test("the slash menu: arrows move, Enter or Tab picks, Esc closes", () => {
  assert.equal(composerKeyAction(key("ArrowDown"), open), "menu-next");
  assert.equal(composerKeyAction(key("ArrowUp"), open), "menu-previous");
  assert.equal(composerKeyAction(key("Enter"), open), "menu-pick");
  assert.equal(composerKeyAction(key("Tab"), open), "menu-pick");
  assert.equal(composerKeyAction(key("Escape"), open), "menu-close");
});

test("the slash menu leaves the input method alone: no pick, no close, no send while composing", () => {
  const composing = { composing: true, menuCount: 3 };
  for (const k of ["Enter", "Tab", "Escape", "ArrowDown", "ArrowUp"]) assert.equal(composerKeyAction(key(k), composing), "none", k);
});

test("Shift+Enter in the open menu breaks the line instead of picking", () => {
  assert.equal(composerKeyAction(key("Enter", { shiftKey: true }), open), "none");
});

test("with the menu closed, arrows and Escape are the textarea's own", () => {
  for (const k of ["ArrowDown", "ArrowUp", "Escape", "Tab"]) assert.equal(composerKeyAction(key(k), closed), "none", k);
});

test("isImeKey reads all three signals", () => {
  assert.equal(isImeKey({ isComposing: false, keyCode: 13 }, false), false);
  assert.equal(isImeKey({ isComposing: true, keyCode: 13 }, false), true);
  assert.equal(isImeKey({ isComposing: false, keyCode: 229 }, false), true);
  assert.equal(isImeKey({ isComposing: false, keyCode: 13 }, true), true);
});
