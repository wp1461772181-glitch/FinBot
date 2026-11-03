import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { BOT_AVATAR_SIZE } from "../src/bot-sizes.mjs";

const css = readFileSync(new URL("../src/grok.css", import.meta.url), "utf8");
const tsx = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");

test("sizes: rail and chat title avatars are 44px+, pickers one step larger", () => {
  assert.ok(BOT_AVATAR_SIZE.rail >= 44 && BOT_AVATAR_SIZE.rail <= 48);
  assert.ok(BOT_AVATAR_SIZE.title >= 44);
  assert.ok(BOT_AVATAR_SIZE.hero > 88);
  assert.ok(BOT_AVATAR_SIZE.createHero > 96);
  assert.ok(BOT_AVATAR_SIZE.emoji > 32);
  assert.ok(BOT_AVATAR_SIZE.mobileFloor >= 40);
});

test("sizes: components use the shared constants, not literals", () => {
  assert.match(tsx("AgentChatPanel.tsx"), /size=\{BOT_AVATAR_SIZE\.title\}/);
  assert.match(tsx("BotPages.tsx"), /size=\{BOT_AVATAR_SIZE\.rail\}/);
  assert.match(tsx("BotPages.tsx"), /size=\{BOT_AVATAR_SIZE\.hero\}/);
  assert.match(tsx("BotPages.tsx"), /size=\{BOT_AVATAR_SIZE\.createHero\}/);
});

test("sizes: css overrides match the constants (title, rail emoji avatar)", () => {
  const title = css.match(/\.agent-title-row \.bot-orb \{ width: (\d+)px; height: (\d+)px; \}/);
  assert.deepEqual(title?.slice(1).map(Number), [BOT_AVATAR_SIZE.title, BOT_AVATAR_SIZE.title]);
  const titleText = css.match(/\.agent-title-row \.bot-avatar \{ width: (\d+)px/);
  assert.equal(Number(titleText?.[1]), BOT_AVATAR_SIZE.title);
  const rail = css.match(/\.bot-rail \.bot-avatar \{ width: (\d+)px; height: (\d+)px/);
  assert.deepEqual(rail?.slice(1).map(Number), [BOT_AVATAR_SIZE.rail, BOT_AVATAR_SIZE.rail]);
});

test("text yields: compact name/subtitle, ellipsis, tight padding, mobile hides secondary text", () => {
  assert.match(css, /\.bot-row-text \{[^}]*min-width: 0[^}]*\}/);
  assert.match(css, /\.bot-row-text strong \{[^}]*font-size: 13px[^}]*text-overflow: ellipsis/);
  assert.match(css, /\.bot-row-text small \{[^}]*font-size: 10px[^}]*text-overflow: ellipsis/);
  assert.match(css, /\.bot-row \{[^}]*gap: 8px[^}]*padding: 4px 6px/);
  assert.match(css, /\.agent-title-row h1 \{[^}]*font-size: 16px[^}]*text-overflow: ellipsis/);
  assert.match(css, /\.agent-title-row \.bot-title \{[^}]*text-overflow: ellipsis/);
  const mobile = css.match(/@media \(max-width: 520px\) \{[^@]*\.agent-title-row \.bot-title \{ display: none; \}/);
  assert.ok(mobile, "narrow screens hide the title subtitle before shrinking the avatar");
  assert.doesNotMatch(css, /@media[^{]*\{[^@]*\.agent-title-row \.bot-orb \{ width: (?:[0-3]\d)px/);
});
