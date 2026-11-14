// The page list.  `name` stays stable across the redesign; `hash` changes when a package moves a route (P2.1: all on the new route map).
//   ready:  a selector that only exists once the page shows its data (string), or an async (page) => void.
//           After it matches, waitReady also waits until no "loading" text is left in the page.
//   before: optional action run after ready and before the screenshot ({ width } is passed along).
import { BOT, ROOT, JUDGMENT, HOLD_MARKER, LOGIN_CODE } from "./fixtures/ids.mjs";

const LOADING = ["正在读取", "正在加载", "读取中", "加载中"];

/** Open the chat page's side panel when it is collapsed (narrow screens start closed). */
async function openSide(page) {
  const toggle = page.locator("button.side-toggle");
  if (await toggle.count() && (await toggle.getAttribute("aria-expanded")) === "false") await toggle.click();
}

/** True from the width where the sidebar is drawn (the `lg` breakpoint); below it the tab bar is. */
const hasSidebar = (width) => width >= 1024;

/** Start an answer in TeslaBot's line that never ends, then go back to the default bot: TeslaBot's row shows 回答中 in the background. */
async function holdTeslaTurn(page) {
  await page.goto(page.url().split("#")[0] + `#/chat/${BOT.teslabot}`, { waitUntil: "load" });
  await page.locator("#agent-draft:not([disabled])").waitFor();
  await page.locator("#agent-draft").fill(`${HOLD_MARKER} AAPL`);
  await page.locator("button.agent-send").click();
  await page.locator("button.agent-stop").waitFor();
  await page.evaluate(() => { location.hash = "#/chat"; });
  await page.locator(".agent-thread .agent-message").first().waitFor();
}
/** On a phone the bot rows are in the 「更多」 drawer. */
async function openMoreDrawer(page) {
  await page.locator('[data-slot="mobile-tab-bar"] button[aria-haspopup="dialog"]').click();
  await page.locator('[data-slot="drawer-content"]').waitFor();
}

export const PAGES = [
  { name: "entry", hash: "#/login", identity: "none", ready: '[aria-labelledby="login-title"]' },
  // The login page after a wrong code, the shell with the sidebar collapsed (1440) / the phone's 更多 drawer open (390),
  // the four marks of a bot row, and the chat as a read-only guest.
  { name: "login-error", hash: "#/login", identity: "none", ready: '[aria-labelledby="login-title"]',
    before: async (page) => { await page.locator('input[type="password"]').fill("not-the-code"); await page.getByRole("button", { name: "登录", exact: true }).click(); await page.locator("#login-error").waitFor(); } },
  { name: "shell-collapsed", hash: "#/chat", ready: ".agent-thread .agent-message",
    before: async (page, { width }) => { if (hasSidebar(width)) { await page.locator('[data-slot="sidebar-trigger"]').click(); await page.waitForFunction(() => document.querySelector('[data-slot="sidebar"]')?.closest("[data-state]")?.getAttribute("data-state") === "collapsed"); } } },
  { name: "shell-mobile-more", hash: "#/chat", ready: ".agent-thread .agent-message",
    before: async (page, { width }) => { if (!hasSidebar(width)) await openMoreDrawer(page); } },
  { name: "shell-bot-states", hash: "#/chat", ready: ".agent-thread .agent-message",
    before: async (page, { width }) => { await holdTeslaTurn(page); if (!hasSidebar(width)) await openMoreDrawer(page); else await page.locator('[data-bot-row][data-marker="running"]').waitFor(); } },
  { name: "guest-chat", hash: "#/chat", identity: "guest", ready: '[data-slot="guest-composer"]' },
  { name: "chat-default", hash: "#/chat", ready: ".agent-thread .agent-message" },
  // Extra views of the default line: the top of the history, and the first answer's step trace opened.
  { name: "chat-default-top", hash: "#/chat", ready: ".agent-thread .agent-message",
    before: async (page) => { await page.evaluate(() => { document.querySelector(".agent-transcript").scrollTop = 0; }); } },
  { name: "chat-default-thinking", hash: "#/chat", ready: ".agent-thread .agent-message",
    before: async (page) => { const toggle = page.locator(".thinking-toggle[aria-expanded]").first(); await toggle.click(); await page.locator(".turn-flow .flow-node").first().waitFor(); await toggle.scrollIntoViewIfNeeded(); } },
  { name: "chat-bot", hash: `#/chat/${BOT.applebot}`, ready: ".agent-thread .agent-message", before: openSide },
  { name: "chat-bot-profile", hash: `#/chat/${BOT.applebot}`, ready: ".agent-thread .agent-message",
    before: async (page) => { await openSide(page); await page.locator("#bot-side").getByRole("tab", { name: "档案" }).click(); } },
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
  { name: "dev-kit-menu", hash: "#/dev/kit", ready: "[data-kit-page]",
    before: async (page) => { await page.locator('[data-kit="menu-trigger"]').click(); await page.locator('[data-slot="dropdown-menu-content"]').waitFor(); } },
];

/** Wait for a page's ready condition, then for any loading text to disappear. */
export async function waitReady(page, def, timeout = 15000) {
  if (typeof def.ready === "function") await def.ready(page);
  else await page.waitForSelector(def.ready, { state: "visible", timeout });
  await page.waitForFunction((phrases) => !phrases.some((p) => (document.body.innerText || "").includes(p)), LOADING, { timeout });
}
