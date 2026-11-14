// The page list.  `name` stays stable across the redesign; `hash` changes when a package moves a route (P2.1: all on the new route map).
//   ready:  a selector that only exists once the page shows its data (string), or an async (page) => void.
//           After it matches, waitReady also waits until no "loading" text is left in the page.
//   before: optional action run after ready and before the screenshot ({ width } is passed along).
import { BOT, ROOT, JUDGMENT } from "./fixtures/ids.mjs";

const LOADING = ["正在读取", "正在加载", "读取中", "加载中"];

/** Open the chat page's side panel when it is collapsed (narrow screens start closed). */
async function openSide(page) {
  const toggle = page.locator("button.side-toggle");
  if (await toggle.count() && (await toggle.getAttribute("aria-expanded")) === "false") await toggle.click();
}

export const PAGES = [
  { name: "entry", hash: "#/login", identity: "none", ready: ".entry-choice" },
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
