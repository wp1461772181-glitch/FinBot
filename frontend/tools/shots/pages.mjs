// The page list.  `name` stays stable across the redesign; `hash` changes when a package moves a route (P2.1: all on the new route map).
//   ready:  a selector that only exists once the page shows its data (string), or an async (page) => void.
//           After it matches, waitReady also waits until no "loading" text is left in the page.
//   before: optional action run after ready and before the screenshot ({ width } is passed along).
import { BOT, CONVERSATION, ROOT, JUDGMENT, HAND_MARKER, HOLD_MARKER, LOGIN_CODE } from "./fixtures/ids.mjs";
import { freshWriteCard, olderTurns, revisionCard } from "./fixtures/chat.mjs";
import { handFed } from "./fake-sse.mjs";

const LOADING = ["正在读取", "正在加载", "读取中", "加载中"];

/** Open the chat page's side panel when it is collapsed (narrow screens start closed). */
async function openSide(page) {
  const toggle = page.locator("[data-testid=side-toggle]");
  if (await toggle.count() && (await toggle.getAttribute("aria-expanded")) === "false") await toggle.click();
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

/** Start an answer in TeslaBot's line that never ends, then go back to the default bot: TeslaBot's row shows 回答中 in the background. */
async function holdTeslaTurn(page) {
  await page.goto(page.url().split("#")[0] + `#/chat/${BOT.teslabot}`, { waitUntil: "load" });
  await page.locator("#agent-draft:not([disabled])").waitFor();
  await page.locator("#agent-draft").fill(`${HOLD_MARKER} AAPL`);
  await clickSend(page);
  await page.locator("[data-testid=stop]").waitFor();
  await page.evaluate(() => { location.hash = "#/chat"; });
  await page.locator("[data-testid=message]").first().waitFor();
}
/** On a phone the bot rows are in the 「更多」 drawer. */
async function openMoreDrawer(page) {
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
  await page.locator('.chat-archive-settings input[type="file"]').setInputFiles({ name: "archive.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(archive)) });
  await page.locator(".chat-archive-settings [role=status]").waitFor({ timeout: 10000 });
  await page.evaluate(() => { location.hash = "#/chat/history"; });
  await page.locator("[data-testid=archive-banner]").waitFor({ timeout: 10000 });
  await page.locator("[data-testid=message][data-role=assistant]").waitFor({ timeout: 10000 });
}

/** The reading of a round's first answer: its message node. */
export const firstAnswer = (page) => page.locator("[data-testid=message][data-role=assistant]").first();

export const PAGES = [
  { name: "entry", hash: "#/login", identity: "none", ready: '[aria-labelledby="login-title"]' },
  // The login page after a wrong code, the shell with the sidebar collapsed (1440) / the phone's 更多 drawer open (390),
  // the four marks of a bot row, and the chat as a read-only guest.
  { name: "login-error", hash: "#/login", identity: "none", ready: '[aria-labelledby="login-title"]',
    before: async (page) => { await page.locator('input[type="password"]').fill("not-the-code"); await page.getByRole("button", { name: "登录", exact: true }).click(); await page.locator("#login-error").waitFor(); } },
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
  { name: "chat-bot", hash: `#/chat/${BOT.applebot}`, ready: "[data-testid=message]", before: openSide },
  { name: "chat-bot-profile", hash: `#/chat/${BOT.applebot}`, ready: "[data-testid=message]",
    before: async (page) => { await openSide(page); await page.locator("#chat-panel").getByRole("tab", { name: "档案" }).click(); await page.locator("[data-testid=profile-pane] .bot-profile").waitFor(); } },
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
    before: async (page) => { await page.locator("[data-testid=model-badge]").click(); await page.locator('[data-slot=pop-panel] [role=radio]').first().waitFor(); } },
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
    before: async (page) => {
      await page.evaluate((id) => { location.hash = `#/chat/${id}`; }, BOT.teslabot);
      await page.locator("h1", { hasText: "TeslaBot" }).waitFor();
      const hand = await handTurn(page, { text: "后台", lead: "后台的回答", botId: BOT.teslabot, conversationId: CONVERSATION.teslabot, turnId: "t9000000-0000-4000-8000-0000000000d2" });
      await page.evaluate(() => { location.hash = "#/chat"; });
      await page.locator("[data-testid=message]").first().waitFor();
      await hand.push(0, "done", { status: "complete", turn_id: "t9000000-0000-4000-8000-0000000000d2", thinking_ms: 900, citations: [], citation_protocol: null }); await hand.close(0);
      await page.locator("[data-sonner-toast]").waitFor({ timeout: 10000 });
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
  { name: "chat-state-archive", hash: "#/settings/data", ready: ".chat-archive-settings", before: async (page) => { await openArchiveView(page); } },
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
  // The conversation page with no bot (#/chat/history): the history list on the left (a drawer below lg, opened by the header's history button), the plain thread.
  { name: "chat-history", hash: "#/chat/history", ready: (page) => page.waitForSelector("[data-testid=history-row]", { state: "attached", timeout: 15000 }) },
  { name: "chat-history-open", hash: "#/chat/history", ready: (page) => page.waitForSelector("[data-testid=history-row]", { state: "attached", timeout: 15000 }),
    before: async (page, { width }) => { if (width < 1024) { await page.locator("[data-testid=history-toggle]").click(); await page.locator("[data-testid=history-list]").waitFor({ state: "visible" }); } } },
  { name: "overview", hash: "#/research/c/AAPL", ready: ".overview-workspace .watch-grid, .overview-workspace" },
  { name: "forecast-home", hash: "#/research/forecasts", ready: ".forecast-home" },
  { name: "forecast-detail", hash: `#/research/forecasts/${ROOT.aapl}`, ready: ".research-brief" },
  { name: "judgment", hash: `#/research/judgments/${JUDGMENT.aapl}`, ready: ".judgment-page h2" },
  { name: "evidence", hash: "#/research/evidence", ready: ".evidence-center" },
  { name: "materials", hash: "#/research/materials", ready: ".material-library-panel h2" },
  { name: "scores", hash: "#/research/scores", ready: "main.workspace h2" },
  { name: "replay", hash: "#/research/replay", ready: ".historical-replay-workspace" },
  { name: "monitor", hash: "#/research/monitor", ready: "main.workspace .v2-desk h2" },
  { name: "portfolio", hash: "#/portfolio", ready: ".pf-positions" },
  { name: "routines", hash: "#/routines", ready: "main.personal-page h1" },
  { name: "news", hash: "#/assistant/news", ready: "main.personal-page h1" },
  { name: "skills", hash: "#/assistant/skills", ready: ".skill-group" },
  { name: "memory", hash: "#/assistant/memory", ready: "main.personal-page h1" },
  { name: "settings", hash: "#/settings/models", ready: ".agent-admin h2" },
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
  { name: "dev-kit-states-confirm", hash: "#/dev/kit/states", ready: "[data-kit-states]", keepLoadingText: true,
    before: async (page) => { await page.locator('[data-kit="confirm-hold"]').click(); await page.locator('[data-slot="alert-dialog-content"]').waitFor(); } },
  // The command palette: opened with the shortcut, with "TS" typed (TSLA from the watch list, then the offer to add TS) and with nothing typed.
  { name: "command-menu", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await page.keyboard.press("Control+k"); await page.locator('[data-slot="command-menu"] input').fill("TS"); await page.locator('[data-slot="command-item"]').first().waitFor(); } },
  { name: "command-menu-all", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page) => { await page.keyboard.press("Control+k"); await page.locator('[data-slot="command-item"]').first().waitFor(); await page.locator('[data-slot="command-menu"] [cmdk-group-heading]', { hasText: "最近对话" }).waitFor(); } },
  // The backend unreachable: every API request fails, then a page that needs the API opens: the banner is at the top of the page.
  { name: "offline", hash: "#/chat", ready: "[data-testid=message]",
    before: async (page, { mock }) => { mock.control.down = true; await page.evaluate(() => { location.hash = "#/portfolio"; }); await page.locator('[data-slot="offline-banner"]').waitFor(); } },
  { name: "dev-kit-menu", hash: "#/dev/kit", ready: "[data-kit-page]",
    before: async (page) => { await page.locator('[data-kit="menu-trigger"]').click(); await page.locator('[data-slot="dropdown-menu-content"]').waitFor(); } },
];

/** Wait for a page's ready condition, then for any loading text to disappear. */
export async function waitReady(page, def, timeout = 15000) {
  if (typeof def.ready === "function") await def.ready(page);
  else await page.waitForSelector(def.ready, { state: "visible", timeout });
  // The states sample page shows skeletons on purpose (their screen-reader text says 正在读取): it opts out of the wait.
  if (def.keepLoadingText) return;
  await page.waitForFunction((phrases) => !phrases.some((p) => (document.body.innerText || "").includes(p)), LOADING, { timeout });
}
