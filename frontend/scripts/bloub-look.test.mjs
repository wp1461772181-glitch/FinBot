import assert from "node:assert/strict";
import test from "node:test";
import { BLOUB_COLORS, faceLook, BLOUB_SHAPES, bloubLook, bloubState, hashString } from "../src/bloub-look.mjs";

test("hashString is stable and non-negative", () => {
  assert.equal(hashString("bot-1"), hashString("bot-1"));
  assert.ok(hashString("x") >= 0);
  assert.notEqual(hashString("a"), hashString("b"));
});

test("a bot's look is stable and drawn from the known shapes/colours", () => {
  const a = bloubLook("bot-123", "bot:kline-idle");
  assert.deepEqual(a, bloubLook("bot-123", "bot:kline-idle"));
  assert.ok(BLOUB_SHAPES.includes(a.shape));
  assert.ok(BLOUB_COLORS.includes(a.color));
});

test("different bots look different (shape+colour pairs spread out)", () => {
  const seen = new Set();
  for (let i = 0; i < 24; i++) { const l = bloubLook(`bot-${i}`, "bot:kline-idle"); seen.add(`${l.shape}/${l.color}`); }
  assert.ok(seen.size >= 12, `only ${seen.size} distinct looks`);
});

test("an explicit non-default face choice maps to a fixed look; legacy/default use the hash", () => {
  const picked = bloubLook("any-id", "bot:square-focus");
  assert.deepEqual(picked, bloubLook("other-id", "bot:square-focus"));
  assert.notDeepEqual(bloubLook("a", "orb:green"), bloubLook("zzzz-b", "orb:green"));
  assert.notDeepEqual(bloubLook("a", ""), bloubLook("zzzz-b", ""));
});

test("state: idle by default, orbit while running, notify when unread and not busy", () => {
  assert.equal(bloubState({}), "idle");
  assert.equal(bloubState({ running: true }), "orbit");
  assert.equal(bloubState({ unread: true }), "notify");
  assert.equal(bloubState({ running: true, unread: true }), "orbit");
});

test("faceLook matches an explicit avatar's look", () => {
  assert.deepEqual(faceLook("square", "focus"), bloubLook("x", "bot:square-focus"));
});
