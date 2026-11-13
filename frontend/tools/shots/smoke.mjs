// Smoke entry: node smoke.mjs --dist <build dir> [--strict]
// One named function per check, registered in CHECKS.  Later phases append checks here.
import { parseArgs } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";
import { summarizeUnmatched } from "./mock-api.mjs";
import { PAGES, waitReady } from "./pages.mjs";
import { BOT } from "./fixtures/ids.mjs";

const { flags } = parseArgs(process.argv.slice(2), { booleans: ["strict"] });
if (!flags.dist) { console.error("usage: node smoke.mjs --dist <build dir> [--strict]"); process.exit(2); }

const unmatched = [];
const SMOKE_TEXT = "请问 AAPL 今天有什么变化？";
const FAKE_ANSWER = "冒烟测试的假回答";

/** Open a fresh view at the default chat page (1440 wide, light) and wait for its history. */
async function openChat(ctx, label) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label, unmatched });
  await view.page.goto(`${ctx.server.url}#agent`, { waitUntil: "load" });
  await waitReady(view.page, PAGES.find((p) => p.name === "chat-default"));
  await settle(view.page);
  return view;
}
/** Open the navigation drawer and press a bot's row. */
async function pressBotRow(page, name) {
  const open = await page.locator(".bot-rail").first().isVisible().catch(() => false);
  if (!open) await page.locator("button.nav-menu-trigger").click();
  await page.locator(".bot-rail .bot-row", { hasText: name }).first().click();
}
const assert = (condition, message) => { if (!condition) throw new Error(message); };

// --- checks ----------------------------------------------------------------------------------------------
async function everyPageOpens(ctx) {
  const bad = [];
  for (const def of PAGES) {
    const view = await newView(ctx.browser, { width: 1440, theme: "light", identity: def.identity ?? "personal", label: def.name, unmatched });
    try {
      await view.page.goto(`${ctx.server.url}${def.hash ?? ""}`, { waitUntil: "load" });
      await waitReady(view.page, def);
      if (view.problems.pageErrors.length) bad.push(`${def.name}: uncaught exception ${view.problems.pageErrors[0].split("\n")[0]}`);
    } catch (error) { bad.push(`${def.name}: ${String(error.message).split("\n")[0]}`); }
    await view.close();
  }
  assert(!bad.length, bad.join("; "));
  return `${PAGES.length} pages ready`;
}

async function sendMessageStreams(ctx) {
  const view = await openChat(ctx, "send-message");
  try {
    const { page } = view;
    await page.locator("#agent-draft").fill(SMOKE_TEXT);
    await page.locator("button.agent-send").click();
    await page.locator(".agent-message.is-user", { hasText: SMOKE_TEXT }).waitFor({ timeout: 10000 });
    await page.locator(".agent-message.is-assistant", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await page.locator("#agent-draft").fill("再问一句");
    assert((await page.locator("#agent-draft").inputValue()) === "再问一句", "composer did not accept input after the turn");
    return "user message, streamed answer, composer usable again";
  } finally { await view.close(); }
}

async function switchBotAndBack(ctx) {
  const view = await openChat(ctx, "switch-bot");
  try {
    const { page } = view;
    await page.locator("#agent-draft").fill(SMOKE_TEXT);
    await page.locator("button.agent-send").click();
    await page.locator(".agent-message.is-assistant", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    const before = await page.evaluate(() => location.hash);
    await pressBotRow(page, "NewsBot");
    await page.waitForFunction((id) => location.hash === `#bot/${id}`, BOT.newsbot, { timeout: 10000 });
    await page.locator("h1", { hasText: "NewsBot" }).waitFor({ timeout: 10000 });
    await pressBotRow(page, "FinBot");
    await page.locator("h1", { hasText: "FinBot" }).waitFor({ timeout: 10000 });
    await page.locator(".agent-message.is-assistant", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    return `${before || "(empty)"} -> #bot/<NewsBot> -> back; earlier answer still present`;
  } finally { await view.close(); }
}

async function backButtonReturns(ctx) {
  const view = await openChat(ctx, "back-button");
  try {
    const { page } = view;
    const start = await page.evaluate(() => location.hash);
    await pressBotRow(page, "NewsBot");
    await page.waitForFunction((id) => location.hash === `#bot/${id}`, BOT.newsbot, { timeout: 10000 });
    await page.goBack();
    await page.waitForFunction((hash) => location.hash === hash, start, { timeout: 10000 });
    await page.locator("h1", { hasText: "FinBot" }).waitFor({ timeout: 10000 });
    return `back to ${start}`;
  } finally { await view.close(); }
}

async function themeToggles(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "theme-toggle", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#admin`, { waitUntil: "load" });
    await page.locator("select#theme").waitFor({ timeout: 10000 });
    const theme = () => page.evaluate(() => document.documentElement.dataset.theme);
    assert((await theme()) === "light", `expected light at start, got ${await theme()}`);
    await page.locator("select#theme").selectOption("dark");
    await page.waitForFunction(() => document.documentElement.dataset.theme === "dark", null, { timeout: 5000 });
    await page.locator("select#theme").selectOption("light");
    await page.waitForFunction(() => document.documentElement.dataset.theme === "light", null, { timeout: 5000 });
    return "light -> dark -> light";
  } finally { await view.close(); }
}

async function thinkingPanelExpands(ctx) {
  const view = await openChat(ctx, "thinking-panel");
  try {
    const { page } = view;
    const toggle = page.locator(".thinking-toggle[aria-expanded]").first();
    await toggle.waitFor({ timeout: 10000 });
    await toggle.click();
    await page.locator(".turn-flow .flow-node").first().waitFor({ timeout: 5000 });
    return `${await page.locator(".turn-flow .flow-node").count()} trace nodes shown`;
  } finally { await view.close(); }
}

/** name -> check.  Add new checks by writing a function above and registering it here. */
export const CHECKS = [
  ["every page opens and reaches its ready condition", everyPageOpens],
  ["send a message: user line, streamed answer, composer reusable", sendMessageStreams],
  ["switch to another bot and back: URL changes, earlier answer kept", switchBotAndBack],
  ["browser back returns to the previous address", backButtonReturns],
  ["theme toggle flips data-theme on <html>", themeToggles],
  ["thinking panel expands to the turn trace", thinkingPanelExpands],
];

const server = await startServer(flags.dist);
const browser = await launch();
let failed = 0;
for (const [name, check] of CHECKS) {
  try { const detail = await check({ browser, server }); console.log(`PASS  ${name}${detail ? `  (${detail})` : ""}`); }
  catch (error) { failed += 1; console.log(`FAIL  ${name}\n      ${String(error?.message ?? error).split("\n").join("\n      ")}`); }
}
await browser.close(); await server.close();

const missing = summarizeUnmatched(unmatched);
if (missing.length) { console.log(`\nunmatched API requests (${missing.length}):`); for (const item of missing) console.log(`  ${item.request}   <- ${item.pages.join(", ")}`); }
else console.log("\nunmatched API requests: none");
console.log(`\n${CHECKS.length - failed} passed, ${failed} failed`);
process.exit(failed || (flags.strict && missing.length) ? 1 : 0);
