// The page list.  `name` stays stable across the redesign; `hash` changes when a package moves a route (P2.1: all on the new route map).
//   ready:  a selector that only exists once the page shows its data (string), or an async (page) => void.
//           After it matches, waitReady also waits until no "loading" text is left in the page.
//   before: optional action run after ready and before the screenshot ({ width } is passed along).
//   view:   options for the browser view ({ fixtureState, motionLevel, reducedMotion ... }), or a function that makes them (a fresh fake backend per picture).
//   mask:   selectors painted over in the picture (a flat grey box): what moves for real under the page's own motion, so that two runs of the page are the same pixels.
//   widths: the widths the page is photographed at when the run asks for them (default: all of them).
import { BOT, CONVERSATION, ROOT, VERSION, JUDGMENT, HAND_MARKER, HOLD_MARKER, LOGIN_CODE } from "./fixtures/ids.mjs";
import { ROOT_IDS } from "./fixtures/forecasts.mjs";
import { freshWriteCard, olderTurns, revisionCard } from "./fixtures/chat.mjs";
import { handFed } from "./fake-sse.mjs";
import { buildState } from "./fixtures/index.mjs";
import { materialId } from "./fixtures/materials.mjs";
import { EXTRA_INBOX, EXTRA_PROPOSALS, EXTRA_TASKS } from "./fixtures/routines.mjs";
import { EXTRA_SOURCES, IMPORT_SAMPLE, KNOWLEDGE_CANDIDATES, KNOWLEDGE_EXTRA_DOCS } from "./fixtures/assistant.mjs";

import fs from "node:fs";
// P9.1: a hook that presses or waits for a LABEL must work in the English interface too (the English run photographs every page): `either("登录")` matches the Chinese label or its English translation, exactly.
const EN_CATALOG = JSON.parse(fs.readFileSync(new URL("../../src/locales/en-US.json", import.meta.url), "utf8"));
const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
export const either = (zh) => new RegExp(`^(${escapeRe(zh)}|${escapeRe(EN_CATALOG[zh] ?? zh)})$`);
export const eitherIn = (zh) => new RegExp(`${escapeRe(zh)}|${escapeRe(EN_CATALOG[zh] ?? zh)}`);

const LOADING = ["正在读取", "正在加载", "读取中", "加载中"];

/** The fake backend's state with TeslaBot hidden from the sidebar (the 全部 bot page lists it last, marked). */
export function stateWithHiddenBot() {
  const state = buildState();
  state.bots.find((b) => b.id === BOT.teslabot).hidden = true;
  return state;
}

/** FP13-c: FinBot's conversation holds a turn that finished while this page was away (its note is in local storage, see the page below). */
export const AWAY_TURN = "t9100000-0000-4000-8000-0000000000a1";
export function stateWithAwayTurn() {
  const state = buildState();
  state.chat.conversations.get(CONVERSATION.finbot).push(
    { role: "user", content: "离开期间问的问题", turn_id: AWAY_TURN },
    { role: "assistant", status: "complete", turn_id: AWAY_TURN, content: "离开期间完成的回答。" });
  return state;
}

/**
 * Open the new-bot dialog the way the width has it: the sidebar's 新建 bot from the desktop's width, the 更多 drawer's from a phone's.  Returns once the dialog is up
 * and its preview is the live body of the personality (a still frame stands in until that chunk arrives).
 */
export async function openNewBotDialog(page, width) {
  if (width >= 1024) await page.locator('[data-slot="sidebar"] button', { hasText: eitherIn("新建 bot") }).first().click();
  else { await openMoreDrawer(page); await page.locator('[data-slot="drawer-content"]').getByRole("button", { name: either("新建 bot") }).click(); }
  await page.locator("[data-testid=new-bot-dialog]").waitFor({ timeout: 15000 });
  await page.locator("[data-testid=new-bot-templates] [data-template]").first().waitFor({ timeout: 15000 });
  await page.locator("[data-testid=new-bot-preview] [data-slot=bot-avatar][data-archetype]").waitFor({ timeout: 15000 });
}

/** Open the chat page's side panel when it is collapsed (narrow screens start closed). */
async function openSide(page) {
  const toggle = page.locator("[data-testid=side-toggle]");
  if (await toggle.count() && (await toggle.getAttribute("aria-expanded")) === "false") await toggle.click();
}

/** The workspace tab's cards are all drawn and none still reads (each card loads on its own). */
export async function workspaceCardsLoaded(page) {
  await page.waitForFunction(() => {
    const pane = document.querySelector("[data-testid=workspace-pane]");
    return Boolean(pane) && pane.querySelectorAll("section[aria-label]").length > 0 && !/正在读取/.test(pane.innerText);
  }, null, { timeout: 20000 });
}

/** Click the first answer's process bar: the panel opens on 过程 with that round's steps. */
async function openProcess(page) {
  await page.locator("[data-testid=message][data-role=assistant]").first().locator("[data-testid=turn-steps]").click();
  await page.locator("[data-testid=timeline-step]").first().waitFor();
}

/** True from the width where the sidebar is drawn (the `lg` breakpoint); below it the tab bar is. */
const hasSidebar = (width) => width >= 1024;

/**
 * Press send once it can be pressed.  On the cold first page of a whole run the button can still be disabled (the history is being restored, or the
 * draft has not reached the state yet), and a click on a disabled button waits for it and then times out: wait for the button to be enabled
 * first, then press.
 */
export async function clickSend(page) {
  await page.waitForFunction(() => { const button = document.querySelector("[data-testid=send]"); return Boolean(button) && !button.disabled; }, null, { timeout: 20000 });
  await page.locator("[data-testid=send]").click({ timeout: 20000 });
}

/**
 * Type into the open line's composer, once it is THAT line's composer.  A hash change does not reload the page: right after switching to another
 * bot the old line's composer is still on screen (enabled, with the old draft) until the new line mounts, and text typed in that gap lands in the
 * old line's draft; the new line's composer then comes up empty and its send button stays disabled.  So when `botName` is given, wait for the
 * composer whose placeholder names that bot (「给 <bot> 发消息…」), type, and check the box holds what was typed before anyone presses send.
 */
export async function fillDraft(page, text, { botName } = {}) {
  if (botName) await page.locator(`#agent-draft[placeholder*="${botName}"]`).waitFor({ state: "visible", timeout: 30000 });
  await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 30000 });
  await page.locator("#agent-draft").fill(text);
  await page.waitForFunction((value) => document.querySelector("#agent-draft")?.value === value, text, { timeout: 10000 });
}

/** Start an answer in TeslaBot's line that never ends, then go back to the default bot: TeslaBot's row shows 回答中 in the background. */
async function holdTeslaTurn(page) {
  await page.goto(page.url().split("#")[0] + `#/chat/${BOT.teslabot}`, { waitUntil: "load" });
  await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 30000 });
  await fillDraft(page, `${HOLD_MARKER} AAPL`, { botName: "TeslaBot" });
  await clickSend(page);
  await page.locator("[data-testid=stop]").waitFor();
  await page.evaluate(() => { location.hash = "#/chat"; });
  await page.locator("[data-testid=message]").first().waitFor();
}
/** On a phone the bot rows are in the 「更多」 drawer. */
export async function openMoreDrawer(page) {
  const more = page.locator('[data-slot="mobile-tab-bar"] button[aria-haspopup="dialog"]');
  await more.waitFor({ state: "visible", timeout: 20000 });
  await more.click({ timeout: 20000 });
  await page.locator('[data-slot="drawer-content"]').waitFor();
}

/** A paragraph of a long streamed answer (Chinese, a few lines at the thread's width, with one bold phrase so the typesetting shows). */
export const streamParagraph = (n) => `第 ${n} 段：这是流式输出中途到达的文字，用来撑出足够的高度，检查视口跟随和「回到底部」。其中 **关键数字 ${100 + n} 亿美元** 用粗体标出，其余是普通叙述，没有来源，也不会触发任何核查标注。\n\n`;

/**
 * Send a hand-fed message in the open line and leave its answer half way: `paragraphs` paragraphs arrived, the stream is still open, and
 * the stop button is where send was.  Returns the hand (push more / close / aborted, see fake-sse.mjs).
 */
export async function streamHalfway(page, { paragraphs = 2, botId = BOT.finbot, conversationId = CONVERSATION.finbot } = {}) {
  const hand = await handFed(page);
  await page.locator("#agent-draft:not([disabled])").waitFor();
  await page.locator("#agent-draft").fill(`${HAND_MARKER} 流式中`);
  await clickSend(page);
  await hand.opened(0);
  await hand.push(0, "conversation", { conversation_id: conversationId, turn_id: "t9000000-0000-4000-8000-0000000000e1", bot_id: botId });
  for (let i = 1; i <= paragraphs; i += 1) await hand.push(0, "delta", { text: streamParagraph(i) });
  await page.locator("[data-testid=stop]").waitFor();
  return hand;
}

/** A trace event as the server sends it (turn-flow.mjs reads these); `fields` set status, ms, output ... */
export const traceEvent = (id, kind, fields = {}) => ({ id, kind, name: null, step: null, status: "done", after: [], start_ms: 0, ms: 300, output: null, ...fields });

/**
 * Send a hand-fed message and leave its turn in the middle of its steps (no text yet): the question, the intent, one decision, two tools
 * that came back (3 and 12 hits) and a third still running.  The stream stays open; returns the hand and the events pushed so far.
 */
export async function streamSteps(page, { botId = BOT.finbot, conversationId = CONVERSATION.finbot } = {}) {
  const hand = await handFed(page);
  await page.locator("#agent-draft:not([disabled])").waitFor();
  await page.locator("#agent-draft").fill(`${HAND_MARKER} 过程条`);
  await clickSend(page);
  await hand.opened(0);
  await hand.push(0, "conversation", { conversation_id: conversationId, turn_id: "t9000000-0000-4000-8000-0000000000f1", bot_id: botId });
  await hand.push(0, "trace", traceEvent("r1", "input", { ms: 10, output: { question: "过程条" } }));
  await hand.push(0, "trace", traceEvent("r2", "classify", { after: ["r1"], start_ms: 20, ms: 700, output: { category: "A", company: "Apple", symbol: "AAPL" } }));
  await hand.push(0, "trace", traceEvent("r3", "decide", { after: ["r2"], step: 1, start_ms: 730, ms: 900, output: { calls: ["query_sec_filings", "query_stock_prices", "query_latest_forecast"] } }));
  await hand.push(0, "trace", traceEvent("r4", "tool", { name: "query_sec_filings", after: ["r3"], start_ms: 1650, ms: 1200, output: { ok: true, count: 3 } }));
  await hand.push(0, "trace", traceEvent("r5", "tool", { name: "query_stock_prices", after: ["r3"], start_ms: 1650, ms: 1500, output: { ok: true, count: 12 } }));
  await hand.push(0, "trace", traceEvent("r6", "tool", { name: "query_latest_forecast", after: ["r3"], start_ms: 1650, ms: null, status: "running" }));
  await page.locator("[data-testid=turn-steps][data-state=running] [data-slot=step-chip]").nth(4).waitFor();
  return hand;
}

/**
 * Send a hand-fed message and open its stream with the line's first events (the conversation, and `lead` as the first text when given).  The stream stays
 * open; returns the hand.  `index` is which hand-fed request this is on the page (0 for the first).
 */
export async function handTurn(page, { text, lead = "", botId = BOT.finbot, conversationId = CONVERSATION.finbot, turnId = "t9000000-0000-4000-8000-0000000000d1", index = 0 } = {}) {
  const hand = await handFed(page);
  await page.locator("#agent-draft:not([disabled])").waitFor();
  await page.locator("#agent-draft").fill(`${HAND_MARKER} ${text}`);
  await clickSend(page);
  await hand.opened(index);
  await hand.push(index, "conversation", { conversation_id: conversationId, turn_id: turnId, bot_id: botId });
  if (lead) await hand.push(index, "delta", { text: lead });
  return hand;
}

/** End a hand-fed turn with a card: the card event, then `done` as waiting_for_input, then the stream closes. */
export async function endWithCard(hand, index, card, turnId = "t9000000-0000-4000-8000-0000000000d1") {
  await hand.push(index, "clarification", card);
  await hand.push(index, "done", { status: "waiting_for_input", turn_id: turnId, thinking_ms: 800, citations: [], citation_protocol: null });
  await hand.close(index);
}

/** End a hand-fed turn as the server ends one that went wrong: an `error` event with its code. */
export async function endWithError(hand, index, code) {
  await hand.push(index, "error", { code });
}

/** Import an archive file on the settings page, then read it on the conversation page: the read-only archive view. */
export async function openArchiveView(page) {
  const stamp = "2026-11-12T08:00:00.000Z";
  const archive = { marker: "market-evidence-agent-chat-archive", version: 1, created_at: stamp, updated_at: stamp,
    conversations: [{ id: "archived-1", created_at: stamp, updated_at: stamp, messages: [{ role: "user", content: "归档里的问题" }, { role: "assistant", content: "归档里的回答", status: "complete" }] }] };
  await page.locator("[data-testid=archive-file-input]").setInputFiles({ name: "archive.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(archive)) });
  await page.locator("[data-testid=archive-status]").waitFor({ timeout: 30000 });
  await page.evaluate(() => { location.hash = "#/chat/history"; });
  await page.locator("[data-testid=archive-banner]").waitFor({ timeout: 30000 });
  await page.locator("[data-testid=message][data-role=assistant]").waitFor({ timeout: 30000 });
}

/** The address of a bot's settings page on one of its sections (P5.1; on a phone the section is the one that starts open). */
export const settingsAt = (botId, section = "profile") => `#/chat/${botId}/settings?section=${section}`;

/** The settings page's 外观与性格 section, once its personality pickers and rehearsal are there (A5 put them in the right panel's 档案 tab; P5.1 moved them here). */
export async function openStudio(page) {
  await page.locator("[data-testid=bot-settings-page] [data-slot=persona-studio] [data-slot=rehearsal]").waitFor({ timeout: 30000 });
  // the preview avatar draws its first frame after its chunk (the body's engine) is in
  await page.locator("[data-testid=rehearsal-stage] svg[data-slot=bot-body]").waitFor({ timeout: 30000 });
  // the preview only runs frames while it is on screen (a body off screen stops): bring it into view, as a reader scrolling to it does
  await page.locator("[data-testid=rehearsal-stage]").scrollIntoViewIfNeeded();
}

/** Unfold a section of the settings page on a phone (a no-op where the sections are all open). */
export async function openSection(page, id) {
  const toggle = page.locator(`[data-testid=section-toggle-${id}]`);
  if (await toggle.count() && (await toggle.getAttribute("aria-expanded")) === "false") await toggle.click();
  await page.locator(`#section-${id}`).scrollIntoViewIfNeeded();
}

/** The reading of a round's first answer: its message node. */
export const firstAnswer = (page) => page.locator("[data-testid=message][data-role=assistant]").first();

/** The five bots' lines, for the pages that show the line's signature. */
const SIGNATURE_LINES = [
  { key: "finbot", bot: BOT.finbot, conversation: CONVERSATION.finbot }, { key: "teslabot", bot: BOT.teslabot, conversation: CONVERSATION.teslabot },
  { key: "newsbot", bot: BOT.newsbot, conversation: CONVERSATION.newsbot }, { key: "applebot", bot: BOT.applebot, conversation: CONVERSATION.applebot },
  { key: "reportbot", bot: BOT.reportbot, conversation: CONVERSATION.reportbot },
];
/** The line carries who is answering (data-archetype, written by a chunk of its own) once the persona has been read: wait for it, so the picture does not depend on the race. */
async function personaReady(page) {
  await page.waitForFunction(() => Boolean(document.querySelector("[data-slot=chat-page]")?.dataset.archetype), null, { timeout: 30000 });
}

/** The fake backend's state with the owner's research queue set to `symbols` (the watchlist page's empty state). */
export function stateWithQueue(symbols) {
  const state = buildState();
  state.queue = [...symbols];
  return state;
}

/** The watchlist page with every row read: each row has its close, its material count and no cell still loading, and the forecast list is in. */
async function watchlistLoaded(page) {
  await page.waitForSelector("[data-testid=watchlist-table] [data-testid=watch-row]", { state: "visible", timeout: 30000 });
  await page.waitForFunction(() => {
    const rows = [...document.querySelectorAll("[data-testid=watch-row]")];
    return rows.length > 0 && rows.every((row) => row.querySelector("[data-testid=watch-close]") && row.querySelector("[data-testid=watch-materials]") && !row.querySelector("[aria-busy=true]"))
      && Boolean(document.querySelector("[data-testid=monitor-chip] [data-slot=status-badge]")) && !/正在读取/.test(document.querySelector("[data-testid=monitor-chip]").innerText);
  }, null, { timeout: 30000 });
}

/** The company overview with its blocks read: the chart is drawn, the judgment card is in, the lists have their rows. */
async function companyLoaded(page) {
  await page.waitForSelector("[data-testid=company-overview]", { state: "visible", timeout: 30000 });
  await page.waitForSelector("[data-testid=company-market] svg.candlestick-chart", { state: "visible", timeout: 30000 });
  await page.waitForSelector("[data-testid=company-judgment] [data-slot=opinion-card]", { state: "visible", timeout: 30000 });
  await page.waitForFunction(() => document.querySelectorAll("[data-testid=company-overview] [aria-busy=true]").length === 0, null, { timeout: 30000 });
}

/** P6.2: the fake backend's state for the forecast pages: no forecasts at all (the empty home), a job that stays running (the task bar), thirteen revision candidates (the cap of ten can be reached). */
export function stateWithForecasts(patch) {
  return Object.assign(buildState(), patch);
}

/** The forecast home with both lanes read: rows in each, the monitor chip and the next-model line in, no block still loading. */
export async function forecastHomeLoaded(page) {
  await page.waitForSelector("[data-testid=forecast-home] [data-slot=formal-row]", { state: "visible", timeout: 30000 });
  await page.waitForSelector("[data-testid=lane-judgment] [data-slot=judgment-row]", { state: "attached", timeout: 30000 });
  await page.waitForFunction(() => Boolean(document.querySelector("[data-testid=monitor-chip] [data-slot=status-badge]")) && !/正在读取/.test(document.querySelector("[data-testid=monitor-chip]").innerText)
    && Boolean(document.querySelector("[data-testid=forecast-next-model]")) && document.querySelectorAll("[data-testid=forecast-home] [aria-busy=true]").length === 0, null, { timeout: 30000 });
}

/** One forecast read through: the judgment card, the chart drawn, every version's record read (the rail's evidence count and difference are numbers, not dots). */
export async function forecastLoaded(page) {
  await page.waitForSelector("[data-testid=forecast-judgment]", { state: "visible", timeout: 30000 });
  await page.waitForSelector("[data-testid=forecast-chart] svg.candlestick-chart", { state: "visible", timeout: 30000 });
  await page.waitForFunction(() => /\d/.test(document.querySelector("[data-testid=rail-evidence]")?.innerText ?? "") && !/…/.test(document.querySelector("[data-testid=rail-diff]")?.innerText ?? "…")
    && document.querySelectorAll("[data-testid=forecast-page] [aria-busy=true]").length === 0, null, { timeout: 30000 });
}

/** The elapsed time of a task is the real clock and no two pictures agree on it: its numbers are not painted (the row keeps its size). */
async function hideElapsed(page) {
  await page.addStyleTag({ content: "[data-elapsed]{color:transparent!important}" });
}

/** Press 发起修订 and wait for the drawer; it opens on the first step. */
export async function openRevise(page) {
  await page.locator("[data-testid=revise-open]").click();
  await page.locator("[data-testid=revise-drawer] [data-testid=revise-step-parent]").waitFor({ timeout: 15000 });
}
/** On to the materials step, with the candidates read. */
export async function toMaterials(page) {
  await page.locator("[data-testid=revise-next]").click();
  await page.locator("[data-testid=revise-step-materials] [data-source]").first().waitFor({ timeout: 15000 });
}
/** Tick the first `count` candidates, in the list's order. */
export async function tickCandidates(page, count) {
  const boxes = page.locator("[data-testid=revise-step-materials] [role=checkbox][aria-checked=false]:not([disabled])");
  for (let i = 0; i < count; i += 1) await boxes.first().click();
  await page.waitForFunction((n) => document.querySelectorAll("[data-testid=revise-step-materials] [role=checkbox][aria-checked=true]").length === n, count, { timeout: 5000 });
}

/** The market colours switched to red up the way the settings page does it (the attribute is what the tokens read). */
async function redUp(page) {
  await page.evaluate(() => { try { localStorage.setItem("market-evidence-agent:updown:v1", "red-up"); } catch { /* storage unavailable */ } document.documentElement.dataset.updown = "red-up"; });
}

// --- P7.1 pictures -------------------------------------------------------------------------------------------------------
const portfolioLoaded = "[data-testid=portfolio-table]";
/**
 * P7.3 (C3).  A full-page picture is taken through Chromium's capture-beyond-viewport, which for a moment makes the layout viewport 1 x 1 and then gives the real size back.
 * Whether the page's own code sees that moment is a race inside the browser (a picture taken at once, or after 500 ms under load, may or may not).  The 记一笔 dialog
 * follows a width query: below 640 px it is a drawer, so on that moment it swaps its shell, the dialog is unmounted and mounted again, and the focus ring
 * comes back on its first field.  The picture is of the dialog undisturbed (focus on 记录), so this view does not pass the capture's transient size on: while the window is
 * narrower than 100 px, `matchMedia(...).matches` keeps the answer it gave at a real size.  Nothing about the page changes at any real size.
 */
async function holdViewportAnswers(page) {
  await page.evaluate(() => {
    const native = window.matchMedia.bind(window); const answers = new Map();
    window.matchMedia = (query) => {
      const list = native(query);
      if (window.innerWidth >= 100) answers.set(query, list.matches);
      return new Proxy(list, { get(target, key) {
        if (key === "matches") { if (window.innerWidth < 100 && answers.has(query)) return answers.get(query); answers.set(query, target.matches); return target.matches; }
        const value = Reflect.get(target, key); return typeof value === "function" ? value.bind(target) : value;
      } });
    };
  });
}
/** The fake backend's state for the portfolio page with switches set (fixtures/portfolio.mjs: empty, fail, referenceOnly, override). */
/** P7.2: the fake backend's state with the extra routines: a task with both price sides, one in a rare time zone, one with an old free-text price line, an expired proposal and a second suggestion. */
export function stateWithRoutines({ tasks = true, expired = true, inbox = true } = {}) {
  const state = buildState();
  if (tasks) state.tasks.push(...structuredClone(EXTRA_TASKS));
  if (expired) state.proposals.push(...structuredClone(EXTRA_PROPOSALS));
  if (inbox) state.inbox.push(...structuredClone(EXTRA_INBOX));
  return state;
}
/** P7.2: nothing waits for the reader (no proposal, no suggested write). */
export function stateWithoutConfirms() {
  const state = buildState();
  state.proposals = []; state.inbox = state.inbox.filter((item) => item.section !== "confirm");
  return state;
}
// P8.1: pieces the pictures of the assistant pages are made of.
const SKILL_DRAWER = "[data-testid=skill-drawer]";
const NEWS_DRAWER = "[data-testid=news-drawer]";
const DRAFT_SKILL = "s3000000-0000-4000-8000-000000000004";
const newsRow = (page, id) => page.locator("[data-testid=news-row]", { has: page.locator(`[data-testid=news-id]`, { hasText: new RegExp(`^${id}$`) }) });
async function openSkillEditor(page, name) {
  await page.locator("[data-testid=skill-card]", { hasText: name }).first().locator("[data-testid=skill-edit]").click();
  await page.locator(SKILL_DRAWER).waitFor({ timeout: 10000 });
  await page.waitForFunction(() => document.querySelector("#skill-name")?.value);
}

/** Throws when the page is wider than its window (a long unbroken string pushed a table out). */
async function noSideScroll(page) {
  const wide = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  if (wide.scroll > wide.inner) throw new Error(`the page scrolls sideways: scrollWidth ${wide.scroll} > innerWidth ${wide.inner}`);
}
/** The fake backend's state for the 后台 page with switches set (fixtures/backstage.mjs: empty, fail). */
export function stateWithBackstage(patch) { const state = buildState(); Object.assign(state.backstage, patch); return state; }
export function stateWithPortfolio(patch) { const state = buildState(); Object.assign(state.portfolio, patch); return state; }

// --- P6.3 pictures ---------------------------------------------------------------------------------------------------
/** The fake backend's state for the material pages: uploads already saved (the dialog's list), a job that never ends (the task bar). */
export function stateWithMaterials(patch) { return Object.assign(buildState(), patch); }

// P8.1: the states of the 助手 pages.  The default state is the fixtures' own (4 skills, 6 profile items, 4 past conversations, 6 news sources, 2 documents, no candidate); these change it the way a page needs.
/** Nothing in any of the four pages: no skill, no profile item, no past conversation, no news source, no document. */
export function stateAssistantEmpty() {
  const state = buildState();
  Object.assign(state.assistant, { skills: [], profile: [], recall: [], docs: [], candidates: [] });
  state.assistant.news.sources = [];
  return state;
}
/** The news page with three more sources: two that can be repaired (one repair fails with a code, one without) and one whose health value the page does not know. */
export function stateWithNewsExtras() {
  const state = buildState();
  state.assistant.news.sources.push(...structuredClone(EXTRA_SOURCES));
  return state;
}
/** The knowledge page with two candidates to review and two more documents (an AI analysis not indexed yet; a withdrawn upload). */
export function stateWithKnowledgeCandidates() {
  const state = buildState();
  state.assistant.candidates = structuredClone(KNOWLEDGE_CANDIDATES);
  state.assistant.docs.push(...structuredClone(KNOWLEDGE_EXTRA_DOCS));
  return state;
}
// P8.2: the states of the 设置 pages.  The default state is the fixtures' own (five catalog models, all saved on the server, all with a key; every role set; Telegram bound; Pushover not set; the material-analysis default a catalog model).
/** The model page with nothing in the catalog (no model, so no role to set). */
export function stateModelsEmpty() {
  const state = buildState();
  Object.assign(state.settings.catalog, { models: [], default: null });
  state.modelRoles = { earnings: null, forecast: null, judge: null };
  state.settings.analysis = { source: "environment", provider: "deepseek", base_url: null, model: "deepseek-chat", has_api_key: false, api_key_last4: null };
  return state;
}
/** The model page with a catalog file on the server: two models that come from it (one reads its key from an environment variable, one has none), one problem in the file, and the default one of them. */
export function stateModelsReadonly() {
  const state = buildState();
  const catalog = state.settings.catalog;
  const file = (name, display_name, provider, model, extra) => ({ name, display_name, provider, model, base_url: null, origin: "file", key_source: "env", key_env: "KIMI_API_KEY", key_status: "configured", is_default: false, migrated: false, ...extra });
  catalog.models.push(file("kimi-k3", "Kimi K3", "kimi", "kimi-k3-preview", { is_default: false }), file("qwen-max", "Qwen Max", "qwen", "qwen-max-latest", { key_env: "QWEN_API_KEY", key_status: "missing" }));
  catalog.config_file = { present: true, problems: ["models[2]: unknown provider"] };
  return state;
}
/** The model page where 测试 is refused with a code the page has a sentence for (the key was not found on the server). */
export function stateModelTestFails() {
  const state = buildState();
  state.settings.testFail = "model_key_missing";
  return state;
}
/** Telegram with no token yet (step 1). */
export function stateTelegramNoToken() {
  const state = buildState();
  state.settings.telegram = { configured: false, has_token: false, bound: false, bot_username: null, chat_id: null, bound_at: null, bind_code_active: false };
  return state;
}
/** Telegram with a token and no binding yet (the code is made on the page). */
export function stateTelegramUnbound() {
  const state = buildState();
  state.settings.telegram = { configured: true, has_token: true, bound: false, bot_username: "finbot_fixture_bot", chat_id: null, bound_at: null, bind_code_active: false };
  return state;
}
/** Pushover set. */
export function statePushoverConfigured() {
  const state = buildState();
  state.settings.pushover = { configured: true, updated_at: "2026-11-10T08:00:00.000Z" };
  return state;
}
const UPLOADED = [
  { id: "u0000000-0000-4000-8000-000000000011", symbol: "AAPL", title: "券商研报：服务业务利润率复盘", source_url: "https://example.com/research/services-margin", published_at: "2026-11-05T08:00:00.000Z", credibility_stars: 4, credibility_reason: "一手数据", impact_severity: "medium", status: "unconfirmed" },
  { id: "u0000000-0000-4000-8000-000000000012", symbol: "AAPL", title: "访谈纪要：供应链负责人", source_url: "https://example.com/interview/supply-chain", published_at: "2026-10-18T03:30:00.000Z", credibility_stars: 2, credibility_reason: "匿名来源", impact_severity: "high", status: "unconfirmed" },
];
/** The replays of the company are listed and the first one's detail is up (a phone lists only). */
const replayLoaded = async (page) => { await page.waitForSelector("[data-testid=replay-row]", { state: "visible", timeout: 30000 }); await page.waitForFunction(() => document.querySelector("[data-testid=replay-detail]") || window.matchMedia("(max-width: 1023px)").matches, null, { timeout: 30000 }); };
/** The monitor's health card is up (the page has read the status). */
/** P7.2: open the task drawer for a new task of the kind, on the section, with the sample content the picture shows. */
export async function openNewTask(page, kind, section) {
  await page.locator("[data-testid=task-new]").first().click();
  const drawer = page.locator("[data-testid=task-drawer]");
  await drawer.waitFor({ timeout: 10000 });
  const go = async (id) => { await drawer.locator(`[data-step-button=${id}]`).click(); await drawer.locator(`[data-testid=task-section-${id}]`).waitFor({ timeout: 5000 }); };
  if (kind === "alerts") { await drawer.locator('[data-testid=task-kind] [data-option=alerts]').click(); await drawer.locator("#task-name").fill("价格线提醒（示例）"); }
  if (section === "time") await go("time");
  if (section === "scope") { await go("scope"); await drawer.locator('[data-testid=task-scope] [data-option=symbols]').click(); await drawer.locator("#task-symbols").fill("AAPL, MSFT"); await drawer.locator("#task-symbols").press("Enter"); await drawer.locator("[data-tag=MSFT]").waitFor({ timeout: 5000 }); }
  if (section === "content") {
    await go("content");
    if (kind === "brief") await drawer.locator("#task-instruction").fill("总结研究队列公司过去一天的新申报和新闻，列出值得注意的变化。");
    else {
      for (let i = 0; i < 3; i++) await drawer.locator("[data-testid=price-add]").click();
      const rows = drawer.locator("[data-testid=price-row]");
      for (const [i, [symbol, side, price]] of [["NVDA", "above", "150"], ["AAPL", "below", "180"], ["TSLA", "above", "200.5"]].entries()) {
        await rows.nth(i).locator("[data-field=symbol]").fill(symbol); await rows.nth(i).locator(`[data-option=${side}]`).click(); await rows.nth(i).locator("[data-field=price]").fill(price);
      }
      await drawer.locator("#task-telegram").click();
    }
  }
  await settled(page);
}
/** P7.2: open the edit drawer of the task card with that name (its 「…」 menu, then 编辑). */
export async function editTask(page, name) {
  const card = page.locator("[data-testid=task-card]", { hasText: name }).first();
  await card.locator("[data-testid=task-menu]").click();
  await page.locator("[data-testid=task-edit]").click();
  await page.locator("[data-testid=task-drawer]").waitFor({ timeout: 10000 });
}
/** The task page's 待你确认 tab shows its cards (their chunk is in) or its empty sentence. */
/** The task drawer is photographed by itself: a whole-page picture of a page taller than the screen resizes the viewport, and the drawer's library (vaul) answers a viewport change by resizing the drawer, so two pictures of the same page could differ. */
const DRAWER = "[data-testid=task-drawer]";
const routinesTasksLoaded = async (page) => { await page.waitForSelector("[data-testid=tasks-list] [data-testid=task-card]", { state: "visible", timeout: 30000 }); };
const routinesLoaded = async (page) => { await page.waitForSelector('[data-testid=confirm-entry] [data-slot="approval-card"], [data-testid=confirm-empty]', { state: "visible", timeout: 30000 }); };
const monitorLoaded = async (page) => { await page.waitForSelector("[data-testid=monitor-health]", { state: "visible", timeout: 30000 }); };
const evidenceLoaded = async (page) => { await page.waitForSelector("[data-testid=evidence-grid] [data-testid=evidence-card]", { state: "visible", timeout: 30000 }); };
/** The library's list is read and (on a wide screen) the first material's detail is up. */
const materialsLoaded = async (page) => {
  await page.waitForSelector("[data-testid=material-row]", { state: "visible", timeout: 30000 });
  if (page.viewportSize().width >= 1024) await page.waitForSelector("[data-testid=material-detail] [data-testid=analysis-card]", { state: "visible", timeout: 30000 });
};
/** Press a row of the list; the detail is on the right (a drawer on a phone). */
export async function openMaterial(page, text) {
  await page.locator("[data-testid=material-row]", { hasText: text }).first().click();
  await page.locator("[data-testid=material-detail]").waitFor({ timeout: 15000 });
}
/** The list shows the page that was asked for (the filters and the offset in force have been answered). */
export async function listReady(page) {
  await page.waitForFunction(() => { const list = document.querySelector("[data-testid=material-list-section]"); return Boolean(list) && list.dataset.wanted === list.dataset.loaded; }, null, { timeout: 15000 });
}
/** Choose one option of a filter select. */
export async function pickFilter(page, key, option) {
  await page.locator(`[data-testid=filter-${key}]`).click();
  await page.getByRole("option", { name: either(option) }).click();
  await listReady(page);
}
const settled = async (page) => { await page.waitForLoadState("networkidle").catch(() => {}); };


export const PAGES = [
  { name: "entry", hash: "#/login", identity: "none", ready: '[aria-labelledby="login-title"]' },
  // The login page after a wrong code, the shell with the sidebar collapsed (1440) / the phone's 更多 drawer open (390),
  // the four marks of a bot row, and the chat as a read-only guest.
  { name: "login-error", hash: "#/login", identity: "none", ready: '[aria-labelledby="login-title"]',
    before: async (page) => { await page.locator('input[type="password"]').fill("not-the-code"); await page.getByRole("button", { name: either("登录") }).click(); await page.locator("#login-error").waitFor(); } },
  { name: "shell-collapsed", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => { if (hasSidebar(width)) { await page.locator('[data-slot="sidebar-trigger"]').click(); await page.waitForFunction(() => document.querySelector('[data-slot="sidebar"]')?.closest("[data-state]")?.getAttribute("data-state") === "collapsed"); } } },
  { name: "shell-mobile-more", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => { if (!hasSidebar(width)) await openMoreDrawer(page); } },
  { name: "shell-bot-states", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => { await holdTeslaTurn(page); if (!hasSidebar(width)) await openMoreDrawer(page); else await page.locator('[data-bot-row][data-marker="running"]').waitFor(); } },
  { name: "guest-chat", hash: "#/chat", identity: "guest", ready: '[data-slot="guest-composer"]' },
  { name: "chat-default", hash: "#/chat", ready: "[data-testid=message]" },
  // Extra views of the default line: the top of the history, and the first answer's step trace opened.
  { name: "chat-default-top", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await page.evaluate(() => { document.querySelector("[data-testid=transcript]").scrollTop = 0; }); } },
  // The first answer's process bar opened: the right panel on 过程 with the round's timeline (P3.3).
  { name: "chat-default-thinking", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await openProcess(page); } },
  // FP13-c: a broken stream of a detached turn: the banner where the answer will appear (no error bar).
  { name: "chat-background-turn", hash: "#/chat", ready: "[data-testid=message]", before: async (page) => {
    const hand = await handFed(page);
    await page.locator("#agent-draft:not([disabled])").waitFor();
    await page.locator("#agent-draft").fill(`${HAND_MARKER} 后台测试`);
    await clickSend(page);
    await hand.opened(0);
    await hand.raw(0, ": detached\n\n");
    await hand.push(0, "conversation", { conversation_id: CONVERSATION.finbot, turn_id: "t9100000-0000-4000-8000-0000000000b1", bot_id: BOT.finbot });
    await hand.push(0, "delta", { text: "等待中的前半句。" });
    await hand.fail(0);
    await page.locator("[data-testid=background-turn]").waitFor({ timeout: 10000 });
  } },
  // FP13-c: a turn that finished while away: its divider, once the restore brings it in (the note is set, then the page reloads).
  { name: "chat-away-done", hash: "#/chat", ready: "[data-testid=message]", view: () => ({ fixtureState: stateWithAwayTurn() }), before: async (page) => {
    await page.evaluate(([key, value]) => window.localStorage.setItem(key, value), [`market-evidence-agent:detached-turn:${CONVERSATION.finbot}:v1`, JSON.stringify({ turnId: AWAY_TURN, question: "离开期间问的问题", at: Date.now() })]);
    await page.reload({ waitUntil: "load" });
    await page.locator("[data-testid=away-divider]").waitFor({ timeout: 15000 });
  } },
  { name: "chat-bot", hash: `#/chat/${BOT.applebot}`, ready: "[data-testid=message]", before: openSide },
  // P3.3: the evidence's home.  A citation chip clicked (the 来源 tab on the second source), the 过程 tab with one step's raw data opened, the process bar
  // of a turn still running (one step turning, two done with their hit counts), a public mark's card open, an answer from before the step graph, the
  // panel folded away.
  { name: "chat-sources", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await firstAnswer(page).locator("[data-testid=citation-chip][data-ordinal='2']").first().click(); await page.locator("[data-slot=source-card][data-highlight]").waitFor(); await page.locator("[data-testid=excerpt-loading]").waitFor({ state: "detached" });
      // The mark lasts under two seconds and the picture is taken after the page settles: keep it on, and take the pointer off the chip (its hover card).
      await page.evaluate(() => { const el = document.querySelector("[data-slot=source-card][data-ordinal='2']"); const keep = () => { if (!el.hasAttribute("data-highlight")) el.setAttribute("data-highlight", ""); }; keep(); new MutationObserver(keep).observe(el, { attributes: true, attributeFilter: ["data-highlight"] }); });
      await page.mouse.move(1, 1); } },
  { name: "chat-process", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await openProcess(page); await page.locator("[data-testid=timeline-step][data-kind=tool] [data-testid=raw-toggle]").first().click(); await page.locator("[data-testid=json-viewer]").first().waitFor(); } },
  { name: "chat-steps-running", hash: "#/chat", ready: "[data-testid=message]", before: async (page) => { await streamSteps(page); } },
  { name: "chat-public-mark", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const mark = page.locator("[data-testid=public-mark]").first(); await mark.scrollIntoViewIfNeeded(); await mark.click(); await page.locator("[data-testid=public-mark-card]").waitFor(); } },
  { name: "chat-old-message", hash: `#/chat/${BOT.applebot}`, ready: "[data-testid=message][data-role=assistant]",
    before: async (page) => { await page.locator("[data-testid=turn-steps][data-state=time]").waitFor(); } },
  { name: "chat-panel-collapsed", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => { if (width >= 1280) await page.locator("[data-testid=panel-close]").click(); await page.locator("[data-testid=context-panel]").waitFor({ state: "detached" }); } },
  // P3.2: the chat's own states.  An answer half way (the stop button in the send position), the same long answer with the reader scrolled up
  // (回到底部 on screen), the "/" command menu, the model badge's panel, and the empty composer with its placeholder.
  { name: "chat-streaming", hash: "#/chat", ready: "[data-testid=message]", before: async (page) => { await streamHalfway(page, { paragraphs: 2 }); } },
  { name: "chat-scrolled-up", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => {
      await streamHalfway(page, { paragraphs: 9 });
      await page.evaluate(() => { const el = document.querySelector("[data-testid=transcript]"); el.scrollTop = Math.round((el.scrollHeight - el.clientHeight) * 0.35); });
      await page.locator("[data-testid=jump-bottom]").waitFor();
    } },
  { name: "chat-slash-menu", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await page.locator("#agent-draft").fill("/"); await page.locator("[data-testid=slash-menu] [role=option]").first().waitFor(); } },
  { name: "chat-model-picker", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await page.locator("[data-testid=model-badge]").click(); await page.locator('[data-testid=model-picker] [role=radio]').first().waitFor(); } },
  // TeslaBot has not spoken yet in the fixtures: its line is empty, the composer is all there is to look at (the empty state's own design is P3.4).
  { name: "chat-empty-composer", hash: `#/chat/${BOT.teslabot}`, ready: "[data-testid=welcome]", before: async (page) => { await page.locator("#agent-draft").focus(); } },
  // P3.4: every row of the design's state table (4.2, 对话页的状态), one page each, named chat-state-<state>; then the confirmation cards in their kinds.
  // 空: TeslaBot has not spoken and watches no company (its real case); AppleBot's line emptied shows the company starters.
  { name: "chat-state-empty", hash: `#/chat/${BOT.teslabot}`, ready: "[data-testid=welcome]", before: async (page) => { await page.locator("[data-testid=starter]").nth(2).waitFor(); } },
  { name: "chat-state-empty-company", hash: `#/chat/${BOT.applebot}`, ready: "[data-testid=message]",
    before: async (page, { mock }) => { mock.state.chat.conversations.set(CONVERSATION.applebot, []); await page.reload({ waitUntil: "load" }); await page.locator("[data-testid=welcome-companies]").waitFor(); await page.locator("[data-testid=starter]").nth(2).waitFor(); } },
  // 恢复历史中: another bot's history is on its way and the skeleton (after 400ms) stands where the messages will be.
  { name: "chat-state-restoring", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { mock }) => {
      mock.control.hold = (method, path) => method === "GET" && /\/conversations\/[^/]+\/messages$/.test(path);
      await page.evaluate((id) => { location.hash = `#/chat/${id}`; }, BOT.newsbot);
      await page.locator("[data-slot=skeleton-frame]").first().waitFor({ timeout: 8000 });
    } },
  // 上滑加载更早消息: the newest page said earlier turns exist; the reader is at the top and the request is still out: the spinner line.
  { name: "chat-state-loading-earlier", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { mock }) => {
      mock.state.chat.older = { [CONVERSATION.finbot]: { messages: olderTurns(6), cursor: 1 } };
      await page.reload({ waitUntil: "load" });
      await page.locator("[data-testid=load-earlier]").waitFor();
      mock.control.hold = (method, path, query) => method === "GET" && /\/messages$/.test(path) && query.get("before") !== null;
      await page.evaluate(() => { const el = document.querySelector("[data-testid=transcript]"); el.scrollTop = 0; });
      await page.locator("[data-testid=load-earlier] svg.animate-spin").waitFor();
    } },
  // 已发出、等首个字: the question is in the line, and under it the bot's head and the bar's first cell (dots, seconds).
  { name: "chat-state-sent", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const hand = await handFed(page); await page.locator("#agent-draft:not([disabled])").waitFor(); await page.locator("#agent-draft").fill(`${HAND_MARKER} 等首个字`); await clickSend(page); await hand.opened(0); await page.locator("[data-testid=pending-answer]").waitFor(); } },
  // 调用工具 / 证据核验: tool chips with their counts, and the 核验 chip turning.
  { name: "chat-state-tools", hash: "#/chat", ready: "[data-testid=message]", before: async (page) => { await streamSteps(page); } },
  { name: "chat-state-verifying", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => {
      const hand = await streamSteps(page);
      await hand.push(0, "trace", traceEvent("r6", "tool", { name: "query_latest_forecast", after: ["r3"], start_ms: 1650, ms: 1800, output: { ok: true, count: 2 } }));
      await hand.push(0, "trace", traceEvent("r7", "verify", { after: ["r4", "r5", "r6"], start_ms: 3500, ms: null, status: "running" }));
      await page.locator("[data-testid=turn-steps][data-state=running] [data-slot=step-chip][data-kind=verify][data-state=running]").waitFor();
    } },
  // 流式输出: half an answer, the caret at its end, the stop button where send was.
  { name: "chat-state-streaming", hash: "#/chat", ready: "[data-testid=message]", before: async (page) => { await streamHalfway(page, { paragraphs: 2 }); } },
  // 等你输入: FinBot's last line is a write confirmation: the card, the amber strip over the input.
  { name: "chat-state-waiting", hash: "#/chat", ready: "[data-slot=approval-card][data-state=active]" },
  // 完成 / 部分完成: a finished answer with its hairline and the folded process bar; the one that ended partially_succeeded.
  { name: "chat-state-done", hash: `#/chat/${BOT.applebot}`, ready: "[data-testid=message][data-role=assistant]", before: async (page) => { await page.locator("[data-testid=done-line]").waitFor(); } },
  { name: "chat-state-partial", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const answer = page.locator("[data-testid=message][data-role=assistant]").nth(1); await answer.scrollIntoViewIfNeeded(); await answer.locator("[data-testid=turn-steps]").waitFor(); } },
  // 失败: what was generated stays, the bar under it says why and offers 重试; a missing key also offers 去设置.
  { name: "chat-state-failed", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const hand = await handTurn(page, { text: "失败", lead: "已经生成的前半句，" }); await endWithError(hand, 0, "provider_timeout"); await page.locator("[data-testid=turn-error]").waitFor(); } },
  { name: "chat-state-failed-settings", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const hand = await handTurn(page, { text: "失败", lead: "已经生成的前半句，" }); await endWithError(hand, 0, "model_key_missing"); await page.locator("[data-testid=turn-error] a").waitFor(); } },
  // 已取消: a grey line 「已停止」, the text kept.
  { name: "chat-state-stopped", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await handTurn(page, { text: "取消", lead: "已经生成的前半句，" }); await page.locator("[data-testid=stop]").click(); await page.locator("[data-testid=stopped-note]").waitFor(); } },
  // 后台回答完成: TeslaBot answers in the background while the reader is in the default line; the toast says so.
  { name: "chat-state-background-done", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => {
      await page.evaluate((id) => { location.hash = `#/chat/${id}`; }, BOT.teslabot);
      await page.locator("h1", { hasText: "TeslaBot" }).waitFor();
      const hand = await handTurn(page, { text: "后台", lead: "后台的回答", botId: BOT.teslabot, conversationId: CONVERSATION.teslabot, turnId: "t9000000-0000-4000-8000-0000000000d2" });
      await page.evaluate(() => { location.hash = "#/chat"; });
      await page.locator("[data-testid=message]").first().waitFor();
      await hand.push(0, "done", { status: "complete", turn_id: "t9000000-0000-4000-8000-0000000000d2", thinking_ms: 900, citations: [], citation_protocol: null }); await hand.close(0);
      // The turn is over for the app once TeslaBot's row says it has something unread (the finished background answer); the toast follows from the same event.
      if (hasSidebar(width)) await page.locator("[data-bot-row][data-marker=unread]", { hasText: "TeslaBot" }).waitFor({ timeout: 30000 }); // a phone has no sidebar rows
      await page.locator("[data-sonner-toast]").waitFor({ timeout: 30000 });
    } },
  // 外部来的新消息: a routine's result and a message from elsewhere arrive while the line is open: each has its divider.
  { name: "chat-state-external-message", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { mock }) => {
      const list = mock.state.chat.conversations.get(CONVERSATION.finbot);
      list.push({ role: "user", content: "【例行任务结果】「收盘复盘」2026-11-13 16:10", turn_id: "t7000000-0000-4000-8000-000000000001" },
        { role: "assistant", status: "complete", turn_id: "t7000000-0000-4000-8000-000000000001", content: "今天收盘后的复盘：关注列表里 5 家上涨、2 家下跌，没有新的申报。" },
        { role: "user", content: "TSLA 的交付数据出来了吗？", turn_id: "t7000000-0000-4000-8000-000000000002" },
        { role: "assistant", status: "complete", turn_id: "t7000000-0000-4000-8000-000000000002", content: "还没有：公司通常在季度结束后的第二天公布交付数据。" });
      await page.locator("[data-testid=external-divider]").nth(1).waitFor({ timeout: 20000 });
    } },
  // 只读归档: the banner on top, 返回当前对话 in place of the input.
  { name: "chat-state-archive", hash: "#/settings/data", ready: "[data-testid=archive-card]", before: async (page) => { await openArchiveView(page); } },
  // 未登录: the input is the sign-in notice.
  { name: "chat-state-guest", hash: "#/chat", identity: "guest", ready: '[data-slot="guest-composer"]' },
  // 离线: the backend is gone; the message that could not be sent is a failed turn with 重试, and the banner is up.
  { name: "chat-state-offline", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { mock }) => {
      mock.control.down = true;
      await page.locator("#agent-draft").fill("离线时发出的问题"); await clickSend(page);
      await page.locator("[data-testid=turn-error]").waitFor({ timeout: 15000 });
      await page.locator('[data-slot="offline-banner"]').waitFor({ timeout: 15000 });
    } },
  // The confirmation cards: a revision card with one of the two materials it needs ticked (its button waits, and says why); the card with nothing to tick;
  // a write confirmation made in this session (its ten minutes show); a card after it was answered (one line).
  { name: "chat-approval-revision", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const hand = await handTurn(page, { text: "修订", lead: "可以用下面这些新材料修订预测，请勾选。" }); await endWithCard(hand, 0, revisionCard()); const card = page.locator("[data-slot=approval-card][data-state=active]"); await card.waitFor(); await card.locator("input[type=checkbox]").first().check(); } },
  { name: "chat-approval-none", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const hand = await handTurn(page, { text: "修订", lead: "这版预测没有可用于修订的新材料。" }); await endWithCard(hand, 0, revisionCard({ candidates: false })); await page.locator("[data-slot=approval-card][data-state=active]").waitFor(); } },
  { name: "chat-approval-countdown", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { const hand = await handTurn(page, { text: "确认", lead: "我可以抓取 AAPL 最新 10-Q 并生成分析，请确认。" }); await endWithCard(hand, 0, freshWriteCard()); await page.locator("[data-slot=approval-timer]").waitFor(); } },
  { name: "chat-approval-answered", hash: "#/chat", ready: "[data-slot=approval-card][data-state=active]",
    before: async (page) => { await page.locator("[data-slot=approval-card] button", { hasText: "确认执行" }).click(); await page.locator("[data-slot=approval-card][data-state=answered]").waitFor(); await page.locator("[data-testid=message][data-role=assistant]", { hasText: "冒烟测试的假回答" }).waitFor(); } },
  // 手机: the bot switcher drawer, the panel as a bottom drawer on the second source, 目录.  (These three only mean something at 390.)
  { name: "chat-mobile-bot-switcher", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => { if (width < 1024) { await page.locator("[data-testid=bot-switcher]").click(); await page.locator("[data-testid=bot-switcher-drawer]").waitFor(); } } },
  { name: "chat-mobile-panel-drawer", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => { if (width < 1024) { await firstAnswer(page).locator("[data-testid=citation-chip][data-ordinal='2']").first().click(); await page.locator("[data-slot=drawer-content] [data-slot=source-card]").first().waitFor(); await page.mouse.move(1, 1); } } },
  { name: "chat-mobile-outline", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { width }) => { if (width < 1024) { await page.locator("[data-testid=outline-button]").click(); await page.locator("[data-testid=outline-drawer] [data-testid=outline-row]").first().waitFor(); } } },
  // P9.1 step 0: the workspace tab's two states that no picture had caught: the edit bar with every card's controls (1440), and the phone's drawer on 工作区 (390).
  { name: "chat-workspace-edit", hash: "#/chat", ready: "[data-testid=message]", widths: [1440],
    before: async (page) => { await workspaceCardsLoaded(page); await page.locator("[data-testid=workspace-pane]").getByRole("button", { name: eitherIn("编辑卡片") }).click(); await page.locator("[data-testid=workspace-pane]").getByRole("button", { name: either("完成") }).waitFor(); await page.mouse.move(1, 1); } },
  { name: "chat-mobile-workspace", hash: "#/chat", ready: "[data-testid=message]", widths: [390],
    before: async (page) => { await page.locator("[data-testid=side-toggle]").click(); await page.locator("[data-slot=drawer-content][data-testid=context-panel]").waitFor({ timeout: 15000 }); await page.locator("[data-testid=tab-workspace]").click(); await workspaceCardsLoaded(page); await page.mouse.move(1, 1); } },
  // The conversation page with no bot (#/chat/history): the history list on the left (a drawer below lg, opened by the header's history button), the plain thread.
  { name: "chat-history", hash: "#/chat/history", ready: (page) => page.waitForSelector("[data-testid=history-row]", { state: "attached", timeout: 15000 }) },
  { name: "chat-history-open", hash: "#/chat/history", ready: (page) => page.waitForSelector("[data-testid=history-row]", { state: "attached", timeout: 15000 }),
    before: async (page, { width }) => { if (width < 1024) { await page.locator("[data-testid=history-toggle]").click(); await page.locator("[data-testid=history-list]").waitFor({ state: "visible" }); } } },
  // P6.1: the old overview is two pages (the names `overview` stops here: its pictures are the watchlist and the company page now).
  // The watchlist: the seven rows with every cell read.  Empty: the server's queue holds nothing.  Row error: one company's price and material reads fail (500) and its row says so with 重试.
  { name: "watchlist", hash: "#/research", ready: watchlistLoaded },
  // The monitor chip in its delayed (action-colour hourglass) state; the monitor page has its own picture, these show it in the top bar of the two pages that carry the chip.
  { name: "watchlist-monitor-delayed", hash: "#/research", ready: watchlistLoaded, view: () => ({ fixtureState: stateWithMaterials({ monitor: "delayed" }) }) },
  { name: "watchlist-red-up", hash: "#/research", ready: watchlistLoaded, before: redUp },
  { name: "watchlist-empty", hash: "#/research", ready: "[data-slot=empty-state]", view: () => ({ fixtureState: stateWithQueue([]) }) },
  { name: "watchlist-row-error", hash: "#/research", ready: watchlistLoaded,
    before: async (page, { mock }) => {
      mock.control.fail = (method, path, query) => (method === "GET" && ((path.endsWith("/v2/stocks/TSLA/prices")) || (path.endsWith("/v3/materials") && query.get("symbol") === "TSLA")) ? 500 : 0);
      await page.evaluate(() => { location.hash = "#/chat"; });
      await page.locator("[data-testid=message]").first().waitFor();
      await page.evaluate(() => { location.hash = "#/research"; });
      await page.locator('[data-testid=watch-row][data-symbol=TSLA] [role=alert]').first().waitFor({ timeout: 15000 });
      await page.waitForFunction(() => document.querySelectorAll("[data-testid=watch-row] [aria-busy=true]").length === 0, null, { timeout: 15000 });
    } },
  // The company page: the overview (chart, latest judgment, recent materials, filings, the four numbers), the two tabs that embed the old pages, a company with no candles
  // (the market card offers 初始化一年行情), an address that is not a ticker, and the overview under red-up.
  { name: "company", hash: "#/research/c/AAPL", ready: companyLoaded },
  { name: "company-red-up", hash: "#/research/c/AAPL", ready: companyLoaded, before: redUp },
  { name: "company-forecasts", hash: "#/research/c/AAPL?tab=forecasts", ready: forecastHomeLoaded },
  { name: "company-materials", hash: "#/research/c/AAPL?tab=materials", ready: materialsLoaded },
  { name: "company-no-prices", hash: "#/research/c/INTC", ready: "[data-testid=init-prices]" },
  { name: "company-unknown", hash: "#/research/c/NOPE12345", ready: "[data-testid=company-unknown]" },
  // P6.2: the forecast pages.  The home (two lanes, the task bar with a job that keeps running, the empty home), one forecast (the newest version, the second, the three
  // tabs under it, the three steps of the revise drawer, the one whose target has passed, the one that cannot be found, one whose revision is being made) and one judgment.
  { name: "forecast-home", hash: "#/research/forecasts", ready: forecastHomeLoaded },
  { name: "forecast-home-monitor-delayed", hash: "#/research/forecasts", ready: forecastHomeLoaded, view: () => ({ fixtureState: stateWithMaterials({ monitor: "delayed" }) }) },
  { name: "forecast-home-empty", hash: "#/research/forecasts", ready: "[data-testid=lane-formal] [data-slot=empty-state]", view: () => ({ fixtureState: stateWithForecasts({ noForecasts: true }) }) },
  { name: "forecast-home-job", hash: "#/research/forecasts", ready: forecastHomeLoaded, view: () => ({ fixtureState: stateWithForecasts({ jobStatus: "running", jobKind: "new" }) }),
    before: async (page) => { await page.locator("[data-testid=forecast-create-go]").click(); await page.locator("[data-testid=forecast-jobs] [data-slot=task-row]").waitFor({ timeout: 15000 });
      // The button shows its check for a moment after the press; the picture is of it at rest (waiting for the job).
      await page.waitForFunction(() => document.querySelector("[data-testid=forecast-create-go]")?.dataset.phase === "idle", null, { timeout: 8000 }); await hideElapsed(page); } },
  { name: "forecast-detail", hash: `#/research/forecasts/${ROOT.aapl}`, ready: forecastLoaded },
  { name: "forecast-detail-v2", hash: `#/research/forecasts/${ROOT.aapl}?version=${VERSION.aapl2}`, ready: forecastLoaded },
  { name: "forecast-detail-compare", hash: `#/research/forecasts/${ROOT.aapl}?section=versions`, ready: forecastLoaded },
  { name: "forecast-detail-evaluation", hash: `#/research/forecasts/${ROOT.aapl}?section=evaluation`, ready: forecastLoaded },
  { name: "forecast-detail-audit", hash: `#/research/forecasts/${ROOT.aapl}?section=audit`, ready: forecastLoaded },
  { name: "forecast-revise-1", hash: `#/research/forecasts/${ROOT.aapl}`, ready: forecastLoaded, before: async (page) => { await openRevise(page); } },
  { name: "forecast-revise-2", hash: `#/research/forecasts/${ROOT.aapl}`, ready: forecastLoaded, view: () => ({ fixtureState: stateWithForecasts({ manyCandidates: true }) }),
    before: async (page) => { await openRevise(page); await toMaterials(page); await tickCandidates(page, 10); } },
  { name: "forecast-revise-3", hash: `#/research/forecasts/${ROOT.aapl}`, ready: forecastLoaded,
    before: async (page) => { await openRevise(page); await toMaterials(page); await tickCandidates(page, 2); await page.locator("[data-testid=revise-next]").click(); await page.locator("[data-testid=revise-step-confirm]").waitFor(); } },
  { name: "forecast-expired", hash: `#/research/forecasts/${ROOT_IDS.nvda}`, ready: async (page) => { await forecastLoaded(page); await page.waitForSelector("[data-testid=revise-reason]", { timeout: 15000 }); } },
  { name: "forecast-missing", hash: "#/research/forecasts/f0000000-0000-4000-8000-0000000000ff", ready: "[data-testid=forecast-missing] [data-slot=empty-state]" },
  { name: "forecast-generating", hash: `#/research/forecasts/${ROOT.aapl}`, ready: forecastLoaded, view: () => ({ fixtureState: stateWithForecasts({ jobStatus: "running" }) }),
    before: async (page) => {
      await openRevise(page); await toMaterials(page); await tickCandidates(page, 1);
      await page.locator("[data-testid=revise-next]").click(); await page.locator("[data-testid=revise-submit]").click();
      await page.locator("[data-testid=forecast-jobs] [data-slot=task-row]").waitFor({ timeout: 15000 });
      await page.locator("[data-testid=revise-drawer]").waitFor({ state: "detached", timeout: 15000 });
      await hideElapsed(page);
    } },
  // P7.3: the `latest` redirect page when the company's forecast list cannot be read (the fake backend's `forecastRootsError` switch): it stops on its error state.
  { name: "latest-error", hash: "#/research/c/AAPL/latest?section=versions", ready: "[data-testid=latest-error] [data-slot=empty-state]", view: () => ({ fixtureState: stateWithForecasts({ forecastRootsError: true }) }) },
  { name: "judgment", hash: `#/research/judgments/${JUDGMENT.aapl}`, ready: async (page) => { await page.waitForSelector("[data-testid=judgment-card]", { timeout: 30000 }); await page.waitForSelector("[data-testid=judgment-revise]", { timeout: 30000 }); await page.waitForFunction(() => document.querySelectorAll("[data-testid=judgment-page] [aria-busy=true]").length === 0, null, { timeout: 30000 }); } },
  // P6.3: the evidence page (the grid of a version's materials, one material in the drawer, the upload dialog with one refused field, a company with no forecast, the
  // version picker open) and the material library (the list with the first material's analysis; the broker note's analysis, original and history; the filter bar with chips;
  // a job under way on the task bar; a filter with no result).  On a phone the detail is a full-screen drawer: the pictures that open one are the phone's drawer form.
  { name: "evidence", hash: "#/research/evidence", ready: evidenceLoaded },
  { name: "evidence-detail", hash: `#/research/evidence/${VERSION.aapl3}/uploaded_media/${materialId(3)}`, ready: async (page) => { await evidenceLoaded(page); await page.waitForSelector("[data-testid=evidence-drawer] [data-testid=event]", { timeout: 30000 }); } },
  { name: "evidence-upload", hash: "#/research/evidence?symbol=AAPL&upload=1", ready: "[data-testid=upload-form]", view: () => ({ fixtureState: stateWithMaterials({ uploaded: { AAPL: UPLOADED } }) }),
    before: async (page) => {
      await page.locator("[data-testid=uploaded-item]").first().waitFor({ timeout: 15000 });
      await page.locator("[data-testid=upload-file]").setInputFiles({ name: "quarterly.csv", mimeType: "text/csv", buffer: Buffer.from("a,b") });
      await page.locator("[data-testid=upload-error-file]").waitFor();
    } },
  { name: "evidence-empty", hash: "#/research/evidence?symbol=MSFT", ready: "[data-testid=evidence-page] [data-slot=empty-state]" },
  { name: "evidence-version-picker", hash: `#/research/evidence/${VERSION.aapl3}`, ready: evidenceLoaded,
    before: async (page) => { await page.locator("[data-testid=crumb-version]").click(); await page.locator("[data-crumb]").first().waitFor(); } },
  { name: "materials", hash: "#/research/materials", ready: materialsLoaded },
  { name: "materials-analysis", hash: "#/research/materials", ready: materialsLoaded, before: async (page) => { await openMaterial(page, "券商研报"); await page.waitForSelector("[data-testid=analysis-card] [data-slot=citation-status][data-kind=unverified]", { timeout: 15000 }); } },
  { name: "materials-raw", hash: "#/research/materials", ready: materialsLoaded,
    before: async (page) => { await openMaterial(page, "券商研报"); await page.locator("[data-testid=analysis-card] [data-testid=citations] button").first().click(); await page.locator("[data-testid=original-quote]").waitFor(); } },
  // P9.1 step 0: an official filing's 原始材料 view with its source address (the broker note of `materials-raw` has none, so no link is drawn there).
  { name: "materials-raw-link", hash: "#/research/materials", ready: materialsLoaded,
    before: async (page) => { await openMaterial(page, "10-Q 0000000000-26-000101"); await page.locator("[data-testid=material-tab-original]").click(); await page.locator("[data-testid=original-link]").waitFor({ timeout: 15000 }); } },
  { name: "materials-history", hash: "#/research/materials", ready: materialsLoaded,
    before: async (page) => { await openMaterial(page, "券商研报"); await page.locator("[data-testid=material-tab-history]").click(); await page.locator("[data-testid=history-view] [data-slot=timeline-item]").first().waitFor(); } },
  { name: "materials-filtered", hash: "#/research/materials", ready: materialsLoaded,
    before: async (page) => { await pickFilter(page, "scope", "全部股票"); await pickFilter(page, "analysisStatus", "已分析"); await page.locator("[data-testid=filter-chip]").nth(1).waitFor(); await page.mouse.move(0, 0); await settled(page); } },   // the pointer is moved off the content (a fact about where it is, not a wait): the last filter choice left it over a row, which painted the hover fill in some runs
  { name: "materials-analyzing", hash: "#/research/materials", ready: materialsLoaded, view: () => ({ fixtureState: stateWithMaterials({ jobHold: true }) }),
    before: async (page) => { await openMaterial(page, "新闻稿：欧盟"); await page.locator("[data-slot=task-row]").waitFor({ timeout: 15000 }); await page.locator("[data-testid=analysis-job]").waitFor(); await hideElapsed(page); } },
  { name: "materials-empty-filter", hash: "#/research/materials", ready: materialsLoaded,
    before: async (page) => { await pickFilter(page, "sourceType", "SEC 官方"); await pickFilter(page, "analysisStatus", "缺少正文"); await page.locator("[data-testid=material-library] [data-slot=empty-state]").waitFor({ timeout: 15000 }); } },
  // P6.4: model scores, historical replays, the automatic monitor.  Each state of the design has its own picture: 样本不足 (scores-insufficient), no replays (replay-empty), a replay
  // under way (replay-running), a replay that ended without a version (replay-failed), one replay open (replay-detail), no monitor record, a late monitor and a failing one.
  { name: "scores", hash: "#/research/scores", ready: "[data-testid=cohort-card]" },
  { name: "scores-insufficient", hash: "#/research/scores", ready: "[data-testid=cohort-card][data-status=insufficient_samples]", view: () => ({ fixtureState: stateWithMaterials({ scoresScored: 12 }) }) },
  { name: "replay", hash: "#/research/replay", ready: replayLoaded },
  { name: "replay-empty", hash: "#/research/replay", ready: "[data-testid=replay-list] [data-slot=empty-state]", view: () => ({ fixtureState: stateWithMaterials({ replayEmpty: true }) }) },
  // P9.1 step 0: the replay page with an EMPTY watchlist (the notice 关注列表为空 + 恢复默认股票).  `replay-empty` above is the other state (no records for a company).
  { name: "replay-empty-watchlist", hash: "#/research/replay", ready: (page) => page.waitForSelector("main [data-slot=empty-state]", { state: "visible", timeout: 30000 }), view: () => ({ fixtureState: stateWithQueue([]) }) },
  { name: "replay-running", hash: "#/research/replay", ready: replayLoaded, view: () => ({ fixtureState: stateWithMaterials({ replayHold: true }) }),
    before: async (page) => { await page.locator("[data-testid=replay-generate]").click(); await page.locator("[data-slot=task-row]").first().waitFor({ timeout: 15000 }); await hideElapsed(page); await settled(page); } },
  { name: "replay-failed", hash: "#/research/replay", ready: replayLoaded, view: () => ({ fixtureState: stateWithMaterials({ replayFail: true, replayRunningPolls: 1, replayError: "forecast_provider_timeout" }) }),
    before: async (page) => { await page.locator("[data-testid=replay-generate]").click(); await page.locator("[data-testid=replay-failure]").waitFor({ timeout: 20000 }); await settled(page); } },
  { name: "replay-detail", hash: "#/research/replay", ready: replayLoaded,
    before: async (page, { width }) => {
      // The third replay (行情不足: no real result yet) shows the pending side of the detail; on a phone the press also opens the full-screen layer.
      await page.locator("[data-testid=replay-row]").nth(2).click();
      await page.waitForFunction(() => document.querySelector("[data-testid=replay-detail]")?.getAttribute("data-version") === "f3000000-0000-4000-8000-000000000003", null, { timeout: 15000 });
      if (width < 1024) await page.locator("[data-testid=replay-drawer]").waitFor({ timeout: 10000 });
      await settled(page);
    } },
  { name: "monitor", hash: "#/research/monitor", ready: monitorLoaded },
  { name: "monitor-no-records", hash: "#/research/monitor", ready: monitorLoaded, view: () => ({ fixtureState: stateWithMaterials({ monitor: "none" }) }) },
  { name: "monitor-delayed", hash: "#/research/monitor", ready: monitorLoaded, view: () => ({ fixtureState: stateWithMaterials({ monitor: "delayed" }) }) },
  { name: "monitor-failing", hash: "#/research/monitor", ready: monitorLoaded, view: () => ({ fixtureState: stateWithMaterials({ monitor: "degraded" }) }) },
  // P7.1: the portfolio page.  The table (a card each on a phone), one position open, the record dialog with one rule broken, the cash being edited, the delete question,
  // nothing recorded, the read failing, and the market colours switched.
  { name: "portfolio", hash: "#/portfolio", ready: portfolioLoaded },
  { name: "portfolio-expanded", hash: "#/portfolio", ready: portfolioLoaded,
    before: async (page) => { await page.locator("[data-testid=pf-toggle]").first().click(); await page.locator("[data-testid=pf-panel] [data-testid=pf-research-forecast]").waitFor({ timeout: 15000 }); } },
  { name: "portfolio-record", hash: "#/portfolio", ready: portfolioLoaded,
    before: async (page) => {
      await holdViewportAnswers(page);
      await page.locator("[data-testid=record-open]").click(); await page.locator("[data-testid=record-dialog]").waitFor({ timeout: 10000 });
      await page.locator("[data-testid=record-submit]").click(); await page.locator("[data-testid=record-error]").waitFor({ timeout: 5000 });
    } },
  { name: "portfolio-edit-cash", hash: "#/portfolio", ready: portfolioLoaded,
    before: async (page) => { await page.locator("[data-testid=cash-edit]").click(); await page.locator("[data-testid=cash-input]").waitFor({ timeout: 5000 }); } },
  { name: "portfolio-delete-confirm", hash: "#/portfolio", ready: portfolioLoaded,
    before: async (page) => { await page.locator("[data-testid=portfolio-ledger] [data-testid=record-delete]").first().click(); await page.locator('[data-slot="alert-dialog-content"]').waitFor({ timeout: 5000 }); } },
  { name: "portfolio-empty", hash: "#/portfolio", ready: "[data-testid=portfolio-empty]", view: () => ({ fixtureState: stateWithPortfolio({ empty: true, cash: "0.00" }) }) },
  { name: "portfolio-error", hash: "#/portfolio", ready: "[data-testid=portfolio-error]", view: () => ({ fixtureState: stateWithPortfolio({ fail: true }) }) },
  { name: "portfolio-red-up", hash: "#/portfolio", ready: portfolioLoaded, before: async (page) => { await redUp(page); await page.locator("[data-testid=pf-toggle]").first().click(); await page.locator("[data-testid=pf-panel]").waitFor({ timeout: 15000 }); } },
  // 后台 (the owner's read-only backstage): the four tabs (a table on a desktop, stacked rows on a phone), a turn open in the drawer (a full course, an old-engine record, a turn that never
  // finished), the usage grouped four ways with its missing prices, and each tab empty and failing.  `ready` is the table (or the empty / error block).
  { name: "backstage-answers", hash: "#/backstage/answers", ready: "[data-testid=answers-table]" },
  { name: "backstage-answers-slow", hash: "#/backstage/answers", ready: "[data-testid=answers-table]",
    before: async (page) => { await page.locator("[data-testid=filter-slow]").check(); await page.locator("[data-testid=filter-high]").check(); await page.locator("[data-testid=answers-table]").waitFor({ timeout: 10000 }); } },
  { name: "backstage-answer-detail", hash: "#/backstage/answers", ready: "[data-testid=answers-table]", element: "[data-testid=answer-drawer]",
    before: async (page) => { await page.locator("[data-testid=answer-open]").nth(1).click(); await page.locator("[data-testid=timeline] [data-step=answer]").waitFor({ timeout: 10000 }); } },
  { name: "backstage-answer-old-engine", hash: "#/backstage/answers", ready: "[data-testid=answers-table]", element: "[data-testid=answer-drawer]",
    before: async (page) => { await page.locator("[data-testid=answer-open]").nth(4).click(); await page.locator("[data-testid=note-old_engine]").waitFor({ timeout: 10000 }); } },
  { name: "backstage-answer-incomplete", hash: "#/backstage/answers", ready: "[data-testid=answers-table]", element: "[data-testid=answer-drawer]",
    before: async (page) => { await page.locator("[data-testid=answer-open]").nth(3).click(); await page.locator("[data-testid=note-incomplete]").waitFor({ timeout: 10000 }); } },
  { name: "backstage-answers-empty", hash: "#/backstage/answers", ready: "[data-testid=backstage-empty]", view: () => ({ fixtureState: stateWithBackstage({ empty: true }) }) },
  { name: "backstage-answers-error", hash: "#/backstage/answers", ready: "[data-slot=error-bar]", view: () => ({ fixtureState: stateWithBackstage({ fail: true }) }) },
  // A token about 300 characters long with no break in it, in a question, a card title and a reminder: the page must not scroll sideways (the picture is taken after the check).
  ...["answers", "operations", "deliveries", "duty"].map((tab) => ({ name: `backstage-${tab}-long`, hash: `#/backstage/${tab}`, ready: `[data-testid=${tab}-table]`, view: () => ({ fixtureState: stateWithBackstage({ long: true }) }),
    before: async (page) => { await page.waitForFunction(() => document.body.innerText.includes("a1b2c3d4a1b2c3d4"), null, { timeout: 10000 }); await noSideScroll(page); } })),
  { name: "backstage-usage", hash: "#/backstage/usage", ready: "[data-testid=usage-table]" },
  ...["model", "bot", "purpose"].map((group) => ({ name: `backstage-usage-${group}`, hash: "#/backstage/usage", ready: "[data-testid=usage-table]",
    before: async (page) => { await page.locator(`[data-testid=usage-group] [data-option=${group}]`).click(); await page.waitForFunction((g) => document.querySelector("[data-testid=usage-table]")?.getAttribute("aria-label")?.includes(g), { model: "按模型", bot: "按 bot", purpose: "按用途" }[group], { timeout: 10000 }).catch(() => {}); await page.locator("[data-testid=usage-table]").waitFor({ timeout: 10000 }); } })),
  { name: "backstage-usage-custom", hash: "#/backstage/usage", ready: "[data-testid=usage-table]",
    before: async (page) => { await page.locator("[data-testid=usage-range] [data-option=custom]").click(); await page.locator("[data-testid=usage-from]").waitFor({ timeout: 10000 }); } },
  { name: "backstage-usage-empty", hash: "#/backstage/usage", ready: "[data-testid=backstage-empty]", view: () => ({ fixtureState: stateWithBackstage({ empty: true }) }) },
  { name: "backstage-usage-error", hash: "#/backstage/usage", ready: "[data-slot=error-bar]", view: () => ({ fixtureState: stateWithBackstage({ fail: true }) }) },
  { name: "backstage-operations", hash: "#/backstage/operations", ready: "[data-testid=operations-table]" },
  { name: "backstage-operations-empty", hash: "#/backstage/operations", ready: "[data-testid=backstage-empty]", view: () => ({ fixtureState: stateWithBackstage({ empty: true }) }) },
  { name: "backstage-operations-error", hash: "#/backstage/operations", ready: "[data-slot=error-bar]", view: () => ({ fixtureState: stateWithBackstage({ fail: true }) }) },
  { name: "backstage-duty", hash: "#/backstage/duty", ready: "[data-testid=duty-table]" },
  { name: "backstage-duty-on", hash: "#/backstage/duty", ready: "[data-testid=duty-table]", view: () => ({ fixtureState: stateWithBackstage({ mode: "on" }) }) },
  { name: "backstage-duty-detail", hash: "#/backstage/duty", ready: "[data-testid=duty-table]", element: "[data-testid=answer-drawer]",
    before: async (page) => { await page.locator("[data-testid=duty-open]").first().click(); await page.locator("[data-testid=timeline] [data-step=answer]").waitFor({ timeout: 10000 }); } },
  { name: "backstage-duty-empty", hash: "#/backstage/duty", ready: "[data-testid=backstage-empty]", view: () => ({ fixtureState: stateWithBackstage({ empty: true }) }) },
  { name: "backstage-duty-error", hash: "#/backstage/duty", ready: "[data-slot=error-bar]", view: () => ({ fixtureState: stateWithBackstage({ fail: true }) }) },
  { name: "backstage-deliveries", hash: "#/backstage/deliveries", ready: "[data-testid=deliveries-table]" },
  { name: "backstage-deliveries-empty", hash: "#/backstage/deliveries", ready: "[data-testid=backstage-empty]", view: () => ({ fixtureState: stateWithBackstage({ empty: true }) }) },
  { name: "backstage-deliveries-error", hash: "#/backstage/deliveries", ready: "[data-slot=error-bar]", view: () => ({ fixtureState: stateWithBackstage({ fail: true }) }) },
  { name: "routines", hash: "#/routines?tab=confirm", ready: routinesLoaded },
  // P7.2: the task page.  The three tabs, the drawer's four sections (a brief; and an alert with three price lines), a task that holds an old free-text price line, a proposal that expired,
  // and nothing waiting.  The default state has one live proposal and one live suggested write; `stateWithRoutines` adds the extra tasks, the expired proposal and a second suggestion.
  { name: "routines-tasks", hash: "#/routines?tab=tasks", ready: routinesTasksLoaded },
  { name: "routines-runs", hash: "#/routines?tab=runs", ready: "[data-testid=runs-pane] [data-slot=timeline-item]" },
  ...["basics", "time", "scope", "content"].map((section, index) => (
    { name: `routines-new-brief-${index + 1}`, hash: "#/routines?tab=tasks", ready: routinesTasksLoaded, element: DRAWER, before: async (page) => { await openNewTask(page, "brief", section); } })),
  { name: "routines-new-alert-content", hash: "#/routines?tab=tasks", ready: routinesTasksLoaded, element: DRAWER, before: async (page) => { await openNewTask(page, "alerts", "content"); } },
  { name: "routines-edit-legacy-priceline", hash: "#/routines?tab=tasks", ready: routinesTasksLoaded, element: DRAWER, view: () => ({ fixtureState: stateWithRoutines() }),
    before: async (page) => { await editTask(page, "旧式价格线"); await page.locator('[data-testid=task-drawer] [data-step-button=content]').click(); await page.locator("[data-testid=task-section-content] [data-testid=price-row]").first().waitFor({ timeout: 10000 }); } },
  { name: "routines-expired", hash: "#/routines?tab=confirm", ready: routinesLoaded, view: () => ({ fixtureState: stateWithRoutines() }) },
  { name: "routines-empty-confirm", hash: "#/routines?tab=confirm", ready: "[data-testid=confirm-empty]", view: () => ({ fixtureState: stateWithoutConfirms() }) },
  // P8.1: the assistant's four pages in the new markup.  `news`, `skills` and `memory` are the old page names (every picture of them changes); the others are new.
  // The default fixtures are the pictures' data: 4 skills (a built-in, an own one, an imported one that is off, a draft), 6 profile items (2 inferred, 1 typed, 1 archived), 4 past conversations, 6 news sources (a degraded one that REA can repair, a failing one, a paused one), 2 documents.
  { name: "news", hash: "#/assistant/news", ready: "[data-testid=news-row]" },
  { name: "skills", hash: "#/assistant/skills", ready: "[data-testid=skill-card]" },
  { name: "memory", hash: "#/assistant/memory", ready: "[data-testid=memory-item]" },
  { name: "skills-edit", hash: "#/assistant/skills", ready: "[data-testid=skill-card]", element: SKILL_DRAWER, before: async (page) => { await openSkillEditor(page, "周日复盘"); } },
  { name: "skills-import-preview", hash: "#/assistant/skills", ready: "[data-testid=skill-card]", element: "[data-testid=skill-import-drawer]", before: async (page) => {
      await page.locator("[data-testid=skill-import-open]").click(); await page.locator("[data-testid=skill-import-text]").fill(IMPORT_SAMPLE);
      await page.locator("[data-testid=skill-import-preview]").click(); await page.locator("[data-testid=skill-preview]").waitFor({ timeout: 10000 });
    } },
  { name: "skills-draft", hash: `#/assistant/skills/${DRAFT_SKILL}`, ready: `${SKILL_DRAWER}[data-draft=true] #skill-name`, element: SKILL_DRAWER, before: async (page) => { await page.waitForFunction(() => document.querySelector("#skill-name")?.value); } },
  { name: "skills-empty", hash: "#/assistant/skills", ready: "[data-testid=skills-empty]", view: () => ({ fixtureState: stateAssistantEmpty() }) },
  { name: "memory-recall", hash: "#/assistant/memory?tab=recall", ready: "[data-testid=recall-item]" },
  { name: "memory-empty", hash: "#/assistant/memory", ready: "[data-testid=memory-empty]", view: () => ({ fixtureState: stateAssistantEmpty() }) },
  { name: "news-test-result", hash: "#/assistant/news", ready: "[data-testid=news-row]", before: async (page) => {
      for (const id of ["wire-markets", "ev-weekly"]) { await newsRow(page, id).locator("[data-testid=news-menu]").click(); await page.locator("[data-testid=news-test]").click(); await newsRow(page, id).locator("[data-testid=news-test-result]").waitFor({ timeout: 10000 }); }
    } },
  { name: "news-edit", hash: "#/assistant/news", ready: "[data-testid=news-row]", element: NEWS_DRAWER, view: () => ({ fixtureState: stateWithNewsExtras() }), before: async (page) => {
      await newsRow(page, "chip-watch").locator("[data-testid=news-menu]").click(); await page.locator("[data-testid=news-edit]").click(); await page.locator(NEWS_DRAWER).waitFor({ timeout: 10000 });
      await page.waitForFunction(() => document.querySelector("#news-name")?.value);
    } },
  { name: "news-new", hash: "#/assistant/news", ready: "[data-testid=news-row]", element: NEWS_DRAWER, before: async (page) => {
      await page.locator("[data-testid=news-new]").click(); await page.locator(NEWS_DRAWER).waitFor({ timeout: 10000 });
      await page.locator("#news-name").fill("Tech Daily Brief"); await page.waitForFunction(() => document.querySelector("#news-id")?.value === "tech-daily-brief");
    } },
  { name: "news-empty", hash: "#/assistant/news", ready: "[data-testid=news-empty]", view: () => ({ fixtureState: stateAssistantEmpty() }) },
  { name: "knowledge", hash: "#/assistant/knowledge", ready: "[data-testid=knowledge-doc]" },
  { name: "knowledge-candidates", hash: "#/assistant/knowledge", ready: "[data-testid=knowledge-candidate]", view: () => ({ fixtureState: stateWithKnowledgeCandidates() }) },
  { name: "knowledge-chunks", hash: "#/assistant/knowledge", ready: "[data-testid=knowledge-doc]", element: "[data-testid=knowledge-drawer]", view: () => ({ fixtureState: stateWithKnowledgeCandidates() }), before: async (page) => {
      await page.locator("[data-testid=knowledge-doc]", { hasText: "AAPL 服务业务分析" }).locator("[data-testid=knowledge-doc-open]").click(); await page.locator("[data-testid=knowledge-chunk]").first().waitFor({ timeout: 10000 });
    } },
  { name: "knowledge-empty", hash: "#/assistant/knowledge", ready: "[data-testid=knowledge-docs-empty]", view: () => ({ fixtureState: stateAssistantEmpty() }) },
  // P8.2: the five settings pages.  `settings` is the model page's whole page (the name stays, so the comparison with the old long page is a changed picture, not a vanished one); the rest are new names.
  { name: "settings", hash: "#/settings/models", ready: "[data-testid=role-row]" },
  { name: "settings-model-new", hash: "#/settings/models", ready: "[data-testid=role-row]", element: "[data-testid=model-dialog]", before: async (page) => {
      await page.locator("[data-testid=model-new]").click(); await page.locator("[data-testid=model-dialog]").waitFor({ timeout: 10000 });
      await page.locator("#model-display").fill("研究助手"); await page.locator("#model-key").fill("fake-key-for-smoke-01");
      await page.waitForFunction(() => /选择列表中的模型|Choose a listed model/.test(document.querySelector("[data-testid=model-discovery-status]")?.textContent ?? "") && !document.querySelector("[data-testid=model-discovered]")?.disabled, null, { timeout: 15000 });
      await page.locator("[data-testid=model-discovered]").click(); await page.getByRole("option", { name: "alpha-1", exact: true }).click();
      await page.waitForFunction(() => document.querySelector("#model-model")?.value === "alpha-1");
    } },
  { name: "settings-model-edit", hash: "#/settings/models", ready: "[data-testid=role-row]", element: "[data-testid=model-dialog]", before: async (page) => {
      await page.locator("[data-testid=model-card][data-model=muse-ember] [data-testid=model-edit]").click(); await page.locator("[data-testid=model-dialog]").waitFor({ timeout: 10000 });
      await page.waitForFunction(() => /选择列表中的模型|Choose a listed model/.test(document.querySelector("[data-testid=model-discovery-status]")?.textContent ?? ""), null, { timeout: 15000 });
    } },
  { name: "settings-model-test-fail", hash: "#/settings/models", ready: "[data-testid=role-row]", element: "[data-testid=model-dialog]", view: () => ({ fixtureState: stateModelTestFails() }), before: async (page) => {
      await page.locator("[data-testid=model-card][data-model=muse-ember] [data-testid=model-edit]").click(); await page.locator("[data-testid=model-dialog]").waitFor({ timeout: 10000 });
      await page.locator("[data-testid=model-test-save]").click(); await page.locator("[data-testid=model-dialog] [data-slot=error-bar]").waitFor({ timeout: 10000 });
      await page.waitForSelector("[data-testid=model-test-save][data-phase=idle]", { timeout: 10000 });
      // the reason is at the foot of the form: bring it into the picture (the form scrolls inside the dialog)
      await page.locator("[data-testid=model-dialog] [data-slot=error-bar]").scrollIntoViewIfNeeded();
    } },
  { name: "settings-roles", hash: "#/settings/models", ready: "[data-testid=role-row]", element: "[data-testid=roles-card]" },
  { name: "settings-models-empty", hash: "#/settings/models", ready: "[data-testid=models-empty]", view: () => ({ fixtureState: stateModelsEmpty() }) },
  { name: "settings-models-readonly", hash: "#/settings/models", ready: "[data-testid=model-readonly-note]", view: () => ({ fixtureState: stateModelsReadonly() }) },
  { name: "settings-models-guest", hash: "#/settings/models", identity: "guest", ready: "[data-testid=settings-guest-note]" },
  { name: "settings-notifications", hash: "#/settings/notifications", ready: "[data-testid=telegram-unbind]" },
  { name: "settings-telegram-token", hash: "#/settings/notifications", ready: "#telegram-token", view: () => ({ fixtureState: stateTelegramNoToken() }) },
  { name: "settings-telegram-waiting", hash: "#/settings/notifications", ready: "[data-testid=telegram-make-code]", view: () => ({ fixtureState: stateTelegramUnbound() }), before: async (page) => {
      // The page asks the status again 5 s after the code is out, and the answer changes the status badge (「… · 正在等待绑定」).  Shooting right after the code made the picture depend on whether those 5 s had passed:
      // wait for the first of those answers (listen BEFORE the click) and for the badge it brings, so the picture is the same however slow the machine is.
      const firstPoll = page.waitForResponse((r) => r.request().method() === "GET" && /\/telegram\/status$/.test(new URL(r.url()).pathname), { timeout: 20000 });
      await page.locator("[data-testid=telegram-make-code]").click(); await page.locator("[data-testid=telegram-waiting]").waitFor({ timeout: 10000 });
      await page.waitForSelector("[data-testid=telegram-make-code][data-phase=idle]", { timeout: 10000 });
      await firstPoll;
      await page.locator("[data-testid=telegram-status]", { hasText: "·" }).waitFor({ timeout: 10000 }); // the badge now carries " · <waiting for the binding>" (no wording here: --locale en-US shoots the same page)
    } },
  { name: "settings-data", hash: "#/settings/data", ready: "[data-testid=archive-card]" },
  { name: "settings-data-archive", hash: "#/settings/data", ready: "[data-testid=archive-card]", before: async (page) => {
      const stamp = "2026-11-12T08:00:00.000Z";
      const archive = { marker: "market-evidence-agent-chat-archive", version: 1, created_at: stamp, updated_at: stamp, conversations: [
        { id: "archived-1", created_at: stamp, updated_at: stamp, messages: [{ role: "user", content: "归档里的问题" }, { role: "assistant", content: "归档里的回答", status: "complete" }] },
        { id: "archived-2", created_at: stamp, updated_at: "2026-11-11T08:00:00.000Z", messages: [{ role: "user", content: "第二个问题" }] }] };
      await page.locator("[data-testid=archive-file-input]").setInputFiles({ name: "archive.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(archive)) });
      await page.locator("[data-testid=archive-view]").waitFor({ timeout: 10000 });
    } },
  { name: "settings-account", hash: "#/settings/account", ready: "[data-testid=account-about]" },
  { name: "settings-account-guest", hash: "#/settings/account", identity: "guest", ready: "[data-testid=account-about]" },
  // Developer sample page of the shadcn components (only in builds with VITE_DEV_KIT=1; fe-check.sh shots/smoke set it).
  // The first shows everything closed; the other two open the Dialog and the DropdownMenu.
  { name: "dev-kit", hash: "#/dev/kit", ready: "[data-kit-page]" },
  { name: "dev-kit-dialog", hash: "#/dev/kit", ready: "[data-kit-page]",
    before: async (page) => { await page.locator('[data-kit="dialog-trigger"]').click(); await page.locator('[data-slot="dialog-content"]').waitFor(); } },
  // The same page with the market colours switched to red up (clicks the page's own toggle).
  { name: "dev-kit-red-up", hash: "#/dev/kit", ready: "[data-kit-page]",
    before: async (page) => { await page.locator('[data-kit="updown-toggle"]').click(); await page.waitForFunction(() => document.documentElement.dataset.updown === "red-up"); } },
  // P2.3: the nine states at #/dev/kit/states (its own address so the pages above stay pixel-identical): everything expanded,
  // the banner lit and a pinned toast with 撤销 on screen; and the same page with the press-and-hold confirmation open.
  { name: "dev-kit-states", hash: "#/dev/kit/states", ready: "[data-kit-states]", keepLoadingText: true,
    before: async (page) => {
      await page.locator('[data-kit="offline-on"]').click(); await page.locator('[data-slot="offline-banner"]').waitFor();
      await page.locator('[data-kit="toast-pinned"]').click(); await page.locator("[data-sonner-toast]").waitFor();
    } },
  // P6.1: the four data components at #/dev/kit/data (its own address), and the same page under red up.
  { name: "dev-kit-data", hash: "#/dev/kit/data", ready: "[data-kit-data]" },
  { name: "dev-kit-data-red-up", hash: "#/dev/kit/data", ready: "[data-kit-data]",
    before: async (page) => { await page.locator('[data-kit="updown-toggle"]').click(); await page.waitForFunction(() => document.documentElement.dataset.updown === "red-up"); } },
  { name: "dev-kit-states-confirm", hash: "#/dev/kit/states", ready: "[data-kit-states]", keepLoadingText: true,
    before: async (page) => { await page.locator('[data-kit="confirm-hold"]').click(); await page.locator('[data-slot="alert-dialog-content"]').waitFor(); } },
  // The command palette: opened with the shortcut, with "TS" typed (TSLA from the watch list, then the offer to add TS) and with nothing typed.
  { name: "command-menu", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await page.keyboard.press("Control+k"); await page.locator('[data-slot="command-menu"] input').fill("TS"); await page.locator('[data-slot="command-item"]').first().waitFor(); } },
  { name: "command-menu-all", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await page.keyboard.press("Control+k"); await page.locator('[data-slot="command-item"]').first().waitFor(); await page.locator('[data-slot="command-menu"] [cmdk-group-heading]', { hasText: eitherIn("最近对话") }).waitFor(); } },
  // The backend unreachable: every API request fails, then a page that needs the API opens: the banner is at the top of the page.
  { name: "offline", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { mock }) => { mock.control.down = true; await page.evaluate(() => { location.hash = "#/portfolio"; }); await page.locator('[data-slot="offline-banner"]').waitFor(); } },
  // P5.1: the bot settings page.  The whole page (a phone: the folded column, the first section open), each section by itself, the save bar up, the leave question,
  // the default bot (no delete, no own Telegram), and a phone with every section open.
  { name: "bot-settings", hash: settingsAt(BOT.applebot), ready: "[data-testid=bot-settings-page]" },
  ...["profile", "focus", "look", "model", "tools", "skills", "routines", "notify", "danger"].map((id) => (
    { name: `bot-settings-${id}`, hash: settingsAt(BOT.applebot, id), ready: "[data-testid=bot-settings-page]", element: `#section-${id}`,
      before: async (page) => {
        await openSection(page, id);
        if (id === "look") await page.locator("[data-slot=persona-studio] [data-slot=rehearsal]").waitFor({ timeout: 30000 });
        if (id === "tools") await page.locator("[data-testid=tool-summary]").waitFor();
        if (id === "skills") await page.locator("[data-testid=skills-list] [data-slot=checkbox]").first().waitFor();
        if (id === "routines") await page.locator("[data-testid=bot-routines] [data-testid=task-card]").first().waitFor({ timeout: 15000 }).catch(() => {});
        if (id === "notify") await page.locator("[data-testid=telegram-panel] [data-slot=stepper]").waitFor();
      } })),
  { name: "bot-settings-dirty", hash: settingsAt(BOT.applebot), ready: "[data-testid=bot-settings-page]",
    before: async (page) => { await page.locator("#bot-name").fill("AppleBot 二号"); await page.locator("[data-testid=save-bar]").waitFor(); } },
  { name: "bot-settings-leave", hash: settingsAt(BOT.applebot), ready: "[data-testid=bot-settings-page]",
    before: async (page, { width }) => {
      await page.locator("#bot-name").fill("AppleBot 二号");
      await page.locator("[data-testid=save-bar]").waitFor();
      if (hasSidebar(width)) await page.locator("[data-bot-row]", { hasText: "NewsBot" }).first().click(); else await page.locator("[data-testid=back-to-chat]").click();
      await page.locator('[data-slot="alert-dialog-content"]').waitFor();
    } },
  { name: "bot-settings-default", hash: settingsAt(BOT.finbot), ready: "[data-testid=bot-settings-page]", before: async (page) => { await openSection(page, "notify"); await openSection(page, "danger"); } },
  { name: "bot-settings-default-danger", hash: settingsAt(BOT.finbot, "danger"), ready: "[data-testid=bot-settings-page]", element: "#section-danger", before: async (page) => { await openSection(page, "danger"); } },
  { name: "bot-settings-open-all", hash: settingsAt(BOT.applebot), ready: "[data-testid=bot-settings-page]",
    before: async (page) => { for (const id of ["focus", "look", "model", "tools", "skills", "routines", "notify", "danger"]) await openSection(page, id); await page.locator("[data-slot=persona-studio] [data-slot=rehearsal]").waitFor({ timeout: 30000 }); await page.evaluate(() => window.scrollTo(0, 0)); } },
  // A5: the personality pickers (archetype, tempo, easing, aura variant, where they come from) and the rehearsal in the settings page's 外观与性格 section (they stood in the right panel's 档案 tab until P5.1): the reduced-motion still frame of
  // each of its states (the shots run with the system's reduced motion), one picture of the whole studio per state.  Then the settings page's animation strength,
  // and the chat page under each level of animation chosen in the app (the browser's own setting left alone): "lite" and "off".
  { name: "bot-settings-persona", hash: settingsAt(BOT.applebot, "look"), ready: "[data-testid=bot-settings-page]", element: "[data-slot=persona-picker]",
    before: async (page) => { await openStudio(page); } },
  { name: "bot-settings-persona-override", hash: settingsAt(BOT.teslabot, "look"), ready: "[data-testid=bot-settings-page]", element: "[data-slot=persona-picker]",
    before: async (page) => { await openStudio(page); await page.locator("[data-testid=persona-archetype] [data-option=reader]").click(); await page.locator("[data-testid=persona-tempo] [data-option=calm]").click(); await page.locator('[data-testid=persona-source][data-kind=override]').waitFor(); } },
  ...["idle", "thinking", "tool3", "verify", "answer", "waiting", "done", "partial", "failed"].map((state) => (
    { name: `bot-settings-rehearsal-${state}`, hash: settingsAt(BOT.teslabot, "look"), ready: "[data-testid=bot-settings-page]", element: "[data-slot=rehearsal]",
      before: async (page) => { await openStudio(page); await page.locator(`[data-slot=rehearsal] [data-scenario=${state}]`).click(); await page.locator(`[data-slot=rehearsal][data-scenario=${state}]`).waitFor(); } })),
  { name: "settings-appearance-motion", hash: "#/settings/appearance", ready: "[data-slot=motion-level]" },
  // (the header's body runs frames for real here: it is the thing "lite" changes, and two runs never stop it at the same moment, so it is painted over; what lite does to the avatar is
  // measured by the smoke checks motion-levels-persist and motion-lite-half-rate)
  { name: "motion-lite", hash: "#/chat", ready: "[data-testid=message]", view: { reducedMotion: "no-preference", motionLevel: "lite" }, mask: ["[data-slot=bot-avatar].bot-orb-live"],
    before: async (page) => { await page.waitForFunction(() => document.documentElement.dataset.motion === "lite"); } },
  { name: "motion-off", hash: "#/chat", ready: "[data-testid=message]", view: { reducedMotion: "no-preference", motionLevel: "off" },
    before: async (page) => { await page.waitForFunction(() => document.documentElement.dataset.motion === "off"); } },
  // A1: the five bots on the sample page, all in the same state; reduced-motion still frames (the face, the look, the badges of the pose).
  ...["idle", "listening", "thinking", "tool", "verify", "answer", "waiting", "done", "partial", "failed", "offline", "sleep"].map((state) => (
    { name: `dev-kit-bots-${state}`, hash: "#/dev/kit/bots", ready: "[data-testid=bots-page]",
      before: async (page) => { await page.locator(`[data-scenario=${state === "tool" ? "tool3" : state}]`).click(); } })),
  // A2: the aura of each of the five bots in the still frames of reduced motion (what the shots run with), one bot's card per picture, light and dark:
  // tool x3, check, done, partial, failed, waiting for you.  Tier M: two examples.
  ...["FinBot", "TeslaBot", "NewsBot", "AppleBot", "ReportBot"].flatMap((bot) => ["tool3", "verify", "done", "partial", "failed", "waiting"].map((scenario) => (
    { name: `dev-kit-aura-${bot.toLowerCase()}-${scenario}`, hash: "#/dev/kit/bots", ready: "[data-testid=bots-page]", element: `[data-testid=bot-sample-${bot}]`,
      before: async (page) => { await page.locator(`[data-scenario=${scenario}]`).click(); } }))),
  ...[["TeslaBot", "tool3"], ["ReportBot", "verify"]].map(([bot, scenario]) => (
    { name: `dev-kit-aura-m-${bot.toLowerCase()}-${scenario}`, hash: "#/dev/kit/bots", ready: "[data-testid=bots-page]", element: `[data-testid=bot-sample-m-${bot}]`,
      before: async (page) => { await page.locator(`[data-scenario=${scenario}]`).click(); } })),
  // A3: the line's signature.  The sample page's row (the trace of thinking, the caret, the closing line; reduced-motion still poses, what shots run with), and the real
  // chat page in each of the five bots' lines: waiting for the first word (the trace), an answer half way (the caret), and a turn that failed (the red line).
  { name: "dev-kit-signature", hash: "#/dev/kit/bots", ready: "[data-testid=signature-row]", element: "[data-testid=signature-row]" },
  ...SIGNATURE_LINES.flatMap(({ key, bot, conversation }) => [
    { name: `chat-sig-wait-${key}`, hash: `#/chat/${bot}`, ready: "#agent-draft:not([disabled])",
      before: async (page) => { await personaReady(page); await handTurn(page, { text: "等首字", botId: bot, conversationId: conversation }); await page.locator("[data-slot=think-trace]").first().waitFor(); } },
    { name: `chat-sig-stream-${key}`, hash: `#/chat/${bot}`, ready: "#agent-draft:not([disabled])",
      before: async (page) => { await personaReady(page); await streamHalfway(page, { paragraphs: 1, botId: bot, conversationId: conversation }); await page.locator("[data-testid=message-body][data-streaming]").first().waitFor(); } },
  ]),
  ...SIGNATURE_LINES.filter(({ key }) => key === "finbot" || key === "reportbot").map(({ key, bot, conversation }) => (
    { name: `chat-sig-failed-${key}`, hash: `#/chat/${bot}`, ready: "#agent-draft:not([disabled])",
      before: async (page) => { await personaReady(page); const hand = await handTurn(page, { text: "失败", lead: "已经生成的前半句，", botId: bot, conversationId: conversation }); await endWithError(hand, 0, "provider_timeout"); await page.locator("[data-testid=done-line][data-state=failed]").waitFor(); } })),
  // P5.2: the new-bot dialog (a dialog at 1440, a full-screen drawer at 390: `widths` says where a page is photographed) and the 全部 bot page.  The shots' random numbers are
  // seeded, so the look the dialog starts from is the same every time.
  { name: "new-bot", hash: "#/chat", ready: "[data-testid=message]", widths: [1440], before: async (page, { width }) => { await openNewBotDialog(page, width); } },
  { name: "new-bot-template", hash: "#/chat", ready: "[data-testid=message]", widths: [1440],
    before: async (page, { width }) => {
      await openNewBotDialog(page, width);
      await page.locator("[data-template=news_monitor]").click();
      await page.locator("[data-testid=new-bot-preview][data-archetype=sentinel]").waitFor();
      await page.locator("[data-testid=new-bot-preview] [data-slot=bot-avatar][data-archetype=sentinel]").waitFor();
    } },
  { name: "new-bot-error", hash: "#/chat", ready: "[data-testid=message]", widths: [1440],
    before: async (page, { width }) => {
      await openNewBotDialog(page, width);
      await page.locator("#new-bot-name").fill("AppleBot");
      await page.locator("[data-testid=new-bot-create]").click();
      await page.locator("[data-testid=new-bot-name-error]").waitFor();
    } },
  { name: "new-bot-mobile", hash: "#/chat", ready: "[data-testid=message]", widths: [390],
    before: async (page, { width }) => {
      await openNewBotDialog(page, width);
      await page.locator("#new-bot-name").fill("读财报二号");
      await page.locator("[data-template=earnings_reader]").click();
      await page.locator("[data-testid=new-bot-preview] [data-slot=bot-avatar][data-archetype=reader]").waitFor();
    } },
  { name: "all-bots", hash: "#/assistant/bots", ready: "[data-testid=bot-card]", widths: [1440], view: () => ({ fixtureState: stateWithHiddenBot() }) },
  { name: "all-bots-mobile", hash: "#/assistant/bots", ready: "[data-testid=bot-card]", widths: [390], view: () => ({ fixtureState: stateWithHiddenBot() }) },
  { name: "dev-kit-menu", hash: "#/dev/kit", ready: "[data-kit-page]",
    before: async (page) => { await page.locator('[data-kit="menu-trigger"]').click(); await page.locator('[data-slot="dropdown-menu-content"]').waitFor(); } },
];


/** Wait for a page's ready condition, then for any loading text to disappear. */
export async function waitReady(page, def, timeout = 30000) {
  if (typeof def.ready === "function") await def.ready(page);
  else await page.waitForSelector(def.ready, { state: "visible", timeout });
  // The states sample page shows skeletons on purpose (their screen-reader text says 正在读取): it opts out of the wait.
  if (def.keepLoadingText) return;
  await page.waitForFunction((phrases) => !phrases.some((p) => (document.body.innerText || "").includes(p)), LOADING, { timeout });
}
