import assert from "node:assert/strict";
import test from "node:test";
import { BOT_MOODS, BOT_STYLES, botAvatar, DEFAULT_AVATAR, nextPose, parseAvatar } from "../src/orb.mjs";

test("avatars: the 16 faces round-trip and fit the server's 16-character cap", () => {
  assert.equal(BOT_STYLES.length * BOT_MOODS.length, 16);
  const all = BOT_STYLES.flatMap((style) => BOT_MOODS.map((mood) => botAvatar(style, mood)));
  assert.equal(new Set(all).size, 16);
  for (const avatar of all) {
    assert.ok(avatar.length <= 16, avatar);
    const [style, mood] = avatar.slice(4).split("-");
    assert.deepEqual(parseAvatar(avatar), { kind: "bot", style, mood });
  }
  assert.equal(DEFAULT_AVATAR, "bot:kline-idle");
  assert.equal(botAvatar("neon", "idle"), DEFAULT_AVATAR);
  assert.deepEqual(parseAvatar("bot:kline-neon", "Apple"), { kind: "text", text: "bot:kline-neon" });
});

test("avatars: older orb colours, the old ★, emoji and blanks", () => {
  assert.deepEqual(parseAvatar("orb:finbot"), { kind: "bot", style: "kline", mood: "idle" });
  assert.deepEqual(parseAvatar("★"), { kind: "bot", style: "kline", mood: "idle" });
  assert.deepEqual(parseAvatar("orb:blue"), { kind: "bot", style: "kline", mood: "focus" });
  assert.deepEqual(parseAvatar("orb:pink"), { kind: "bot", style: "kline", mood: "bull" });
  assert.deepEqual(parseAvatar("orb:gray"), { kind: "bot", style: "kline", mood: "mono" });
  assert.deepEqual(parseAvatar("orb:neon", "Apple"), { kind: "text", text: "orb:neon" });
  assert.deepEqual(parseAvatar("orb:constructor", "Apple"), { kind: "text", text: "orb:constructor" });
  assert.deepEqual(parseAvatar("📈"), { kind: "text", text: "📈" });
  assert.deepEqual(parseAvatar("", "Apple"), { kind: "text", text: "A" });
});

test("brand poses: the next pose is never the current one and every pose is reachable", () => {
  for (let current = 0; current < 3; current++) {
    const seen = new Set([0, 0.4, 0.6, 0.999].map((r) => nextPose(current, 3, () => r)));
    assert.ok(!seen.has(current));
    assert.equal(seen.size, 2);
  }
});
