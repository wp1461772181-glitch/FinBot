// The page list.  `name` stays stable across the redesign; `hash` changes when a package moves a route (P2.1: all on the new route map).
//   ready:  a selector that only exists once the page shows its data (string), or an async (page) => void.
//           After it matches, waitReady also waits until no "loading" text is left in the page.
//   before: optional action run after ready and before the screenshot ({ width } is passed along).
import { BOT, CONVERSATION, ROOT, JUDGMENT, HAND_MARKER, HOLD_MARKER, LOGIN_CODE } from "./fixtures/ids.mjs";
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

/** Start an answer in TeslaBot's line that never ends, then go back to the default bot: TeslaBot's row shows 回答中 in the background. */
async function holdTeslaTurn(page) {
  await page.goto(page.url().split("#")[0] + `#/chat/${BOT.teslabot}`, { waitUntil: "load" });
  await page.locator("#agent-draft:not([disabled])").waitFor();
  await page.locator("#agent-draft").fill(`${HOLD_MARKER} AAPL`);
  await page.locator("[data-testid=send]").click();
  await page.locator("[data-testid=stop]").waitFor();
  await page.evaluate(() => { location.hash = "#/chat"; });
  await page.locator("[data-testid=message]").first().waitFor();
}
/** On a phone the bot rows are in the 「更多」 drawer. */
async function openMoreDrawer(page) {
  await page.locator('[data-slot="mobile-tab-bar"] button[aria-haspopup="dialog"]').click();
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
  await page.locator("[data-testid=send]").click();
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
  await page.locator("[data-testid=send]").click();
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
