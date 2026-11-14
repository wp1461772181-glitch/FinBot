import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { BOT_AVATAR_SIZE } from "../src/bot-sizes.mjs";

const css = readFileSync(new URL("../src/styles/legacy/grok.css", import.meta.url), "utf8");
const tsx = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");

// A1: the sizes are the four tiers of design 6.2 (XS <= 24, S 28-40, M 48-64, L 96-160). `rail` (48, used by nothing since P2.2) left the
// table; `message` (24, the XS size of a message head) joined it.
import { BOT_TIERS, FULL_TIERS, tierOf } from "../src/bot-sizes.mjs";
test("sizes: every avatar size lies in the tier it is meant for; pickers one step larger", () => {
  assert.equal(tierOf(BOT_AVATAR_SIZE.message), "XS");
  assert.equal(tierOf(BOT_AVATAR_SIZE.sidebar), "S");
  assert.equal(tierOf(BOT_AVATAR_SIZE.sidebar - 4), "S", "the sidebar row draws it 4px smaller");
  assert.equal(tierOf(BOT_AVATAR_SIZE.title), "M", "the chat header's live bot");
  assert.ok(BOT_AVATAR_SIZE.title >= 44);
  for (const key of ["hero", "createHero", "login"]) assert.equal(tierOf(BOT_AVATAR_SIZE[key]), "L", key);
  assert.ok(BOT_AVATAR_SIZE.hero > 88);
  assert.ok(BOT_AVATAR_SIZE.createHero > 96);
  assert.ok(BOT_AVATAR_SIZE.emoji > 32);
  assert.ok(BOT_AVATAR_SIZE.mobileFloor >= 40);
  assert.ok(BOT_AVATAR_SIZE.sidebar >= BOT_TIERS.S.min && BOT_AVATAR_SIZE.sidebar <= BOT_TIERS.S.max, "the sidebar avatar is size S");
  assert.ok(BOT_AVATAR_SIZE.login >= BOT_TIERS.L.min, "the login page's FinBot is size L");
  assert.equal(BOT_AVATAR_SIZE.rail, undefined);
});

test("tiers: the ranges of 6.2, edges and gaps; only M and L run a loop for themselves", () => {
  assert.deepEqual(BOT_TIERS, { XS: { min: 1, max: 24 }, S: { min: 28, max: 40 }, M: { min: 48, max: 64 }, L: { min: 96, max: 160 } });
  for (const [tier, { min, max }] of Object.entries(BOT_TIERS)) { assert.equal(tierOf(min), tier); assert.equal(tierOf(max), tier); }
  assert.deepEqual([tierOf(25), tierOf(26), tierOf(27), tierOf(44), tierOf(45), tierOf(80), tierOf(81)], ["XS", "XS", "S", "S", "M", "M", "L"]);
  assert.equal(tierOf(NaN), "XS"); assert.equal(tierOf(undefined), "XS"); assert.equal(tierOf(1000), "L");
  assert.deepEqual(FULL_TIERS, ["M", "L"]);
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
