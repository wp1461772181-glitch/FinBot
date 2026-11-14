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

test("sizes: the chat title avatar is sized by the constant for a bot orb and for an emoji box (P3.2: the .agent-title-row rules left the old sheet with the old header)", () => {
  const header = tsx("app/chat/ChatHeader.tsx");
  assert.match(header, /"--avatar": `\$\{BOT_AVATAR_SIZE\.title\}px`/);
  assert.match(header, /\[&_\.bot-avatar\]:h-\[var\(--avatar\)\] \[&_\.bot-avatar\]:w-\[var\(--avatar\)\]/);
  assert.doesNotMatch(css, /\.agent-title-row/);
  assert.doesNotMatch(css, /\.bot-rail/);
});

test("text yields: the chat title keeps its ellipsis and hides the subtitle on narrow screens before the avatar shrinks", () => {
  const header = tsx("app/chat/ChatHeader.tsx");
  assert.match(header, /<h1 id="chat-title" className="truncate /);
  assert.match(header, /data-testid="chat-subtitle" className="truncate [^"]*max-sm:hidden"/);
  assert.match(header, /className="flex shrink-0 \[&_\.bot-avatar\]/, "the avatar box never shrinks");
});
