import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { BOT_AVATAR_SIZE } from "../src/bot-sizes.mjs";

const css = readFileSync(new URL("../src/styles/legacy/grok.css", import.meta.url), "utf8");
const tsx = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");

test("sizes: rail and chat title avatars are 44px+, pickers one step larger", () => {
  assert.ok(BOT_AVATAR_SIZE.rail >= 44 && BOT_AVATAR_SIZE.rail <= 48);
  assert.ok(BOT_AVATAR_SIZE.title >= 44);
  assert.ok(BOT_AVATAR_SIZE.hero > 88);
  assert.ok(BOT_AVATAR_SIZE.createHero > 96);
  assert.ok(BOT_AVATAR_SIZE.emoji > 32);
  assert.ok(BOT_AVATAR_SIZE.mobileFloor >= 40);
  assert.ok(BOT_AVATAR_SIZE.sidebar >= 28 && BOT_AVATAR_SIZE.sidebar <= 40, "the sidebar avatar is size S");
  assert.ok(BOT_AVATAR_SIZE.login >= 96, "the login page's FinBot is size L");
});

test("sizes: components use the shared constants, not literals", () => {
  assert.match(tsx("app/chat/ChatHeader.tsx"), /size=\{BOT_AVATAR_SIZE\.title\}/);   // P3.1: moved out of AgentChatPanel.tsx
  assert.match(tsx("app/shell/BotRow.tsx"), /BOT_AVATAR_SIZE\.sidebar/);   // P2.2: the sidebar row (design 6.2, size S: 28-40px) replaced the rail row
  assert.match(tsx("BotSidePanel.tsx"), /size=\{BOT_AVATAR_SIZE\.hero\}/);   // P3.1: BotPages.tsx was split; the profile form is in BotSidePanel.tsx
  assert.match(tsx("BotSidePanel.tsx"), /size=\{BOT_AVATAR_SIZE\.createHero\}/);
});

test("sizes: css overrides match the constants (title; the rail emoji avatar rule went with the old rail in P2.2)", () => {
  const title = css.match(/\.agent-title-row \.bot-orb \{ width: (\d+)px; height: (\d+)px; \}/);
  assert.deepEqual(title?.slice(1).map(Number), [BOT_AVATAR_SIZE.title, BOT_AVATAR_SIZE.title]);
  const titleText = css.match(/\.agent-title-row \.bot-avatar \{ width: (\d+)px/);
  assert.equal(Number(titleText?.[1]), BOT_AVATAR_SIZE.title);
  assert.doesNotMatch(css, /\.bot-rail/);
});

test("text yields: the chat title row keeps its ellipsis and hides the subtitle on narrow screens (the rail row rules went with the old rail in P2.2)", () => {
  assert.match(css, /\.agent-title-row h1 \{[^}]*font-size: 16px[^}]*text-overflow: ellipsis/);
  assert.match(css, /\.agent-title-row \.bot-title \{[^}]*text-overflow: ellipsis/);
  const mobile = css.match(/@media \(max-width: 520px\) \{[^@]*\.agent-title-row \.bot-title \{ display: none; \}/);
  assert.ok(mobile, "narrow screens hide the title subtitle before shrinking the avatar");
  assert.doesNotMatch(css, /@media[^{]*\{[^@]*\.agent-title-row \.bot-orb \{ width: (?:[0-3]\d)px/);
});
