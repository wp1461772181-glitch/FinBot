// Smoke entry: node smoke.mjs --dist <build dir> [--strict] [--only <text in a check's name>]
// One named function per check, registered in CHECKS.  Later phases append checks here.
import { parseArgs } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";
import { summarizeUnmatched } from "./mock-api.mjs";
import { PAGES, waitReady } from "./pages.mjs";
import { BOT, CONVERSATION, JUDGMENT, LOGIN_CODE, ROOT, VERSION } from "./fixtures/ids.mjs";
import { INBOX, PROPOSALS } from "./fixtures/routines.mjs";
import { MATERIALS } from "./fixtures/materials.mjs";
import { buildState } from "./fixtures/index.mjs";
import path from "node:path";
import { findCollisions } from "./collisions.mjs";

const { flags } = parseArgs(process.argv.slice(2), { booleans: ["strict"] });
if (!flags.dist) { console.error("usage: node smoke.mjs --dist <build dir> [--strict]"); process.exit(2); }

const unmatched = [];
const SMOKE_TEXT = "请问 AAPL 今天有什么变化？";
const FAKE_ANSWER = "冒烟测试的假回答";

/** Open a fresh view at the default chat page (1440 wide, light) and wait for its history. */
async function openChat(ctx, label) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label, unmatched });
  await view.page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
  await waitReady(view.page, PAGES.find((p) => p.name === "chat-default"));
  await settle(view.page);
  return view;
}
/** Press a bot's row in the sidebar (P2.2: the sidebar is always drawn at 1440; the old drawer and its toggle are gone). */
async function pressBotRow(page, name) {
  await page.locator("[data-bot-row]", { hasText: name }).first().click();
}
/** Press one of the sidebar's page entries (持仓, 任务, 研究 ...). */
async function pressNavItem(page, name) {
  await page.locator('[data-slot="sidebar"] a', { hasText: name }).first().click();
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
    await page.waitForFunction((id) => location.hash === `#/chat/${id}`, BOT.newsbot, { timeout: 10000 });
    await page.locator("h1", { hasText: "NewsBot" }).waitFor({ timeout: 10000 });
    await pressBotRow(page, "FinBot");
    await page.locator("h1", { hasText: "FinBot" }).waitFor({ timeout: 10000 });
    await page.locator(".agent-message.is-assistant", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    return `${before || "(empty)"} -> #/chat/<NewsBot> -> back; earlier answer still present`;
  } finally { await view.close(); }
}

async function backButtonReturns(ctx) {
  const view = await openChat(ctx, "back-button");
  try {
    const { page } = view;
    const start = await page.evaluate(() => location.hash);
    await pressBotRow(page, "NewsBot");
    await page.waitForFunction((id) => location.hash === `#/chat/${id}`, BOT.newsbot, { timeout: 10000 });
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
    await page.goto(`${ctx.server.url}#/settings/appearance`, { waitUntil: "load" });
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

/** Legacy selectors that may match shadcn parts because the match is known to change nothing.  Keep this list short and justified. */
const SELECTOR_MATCH_ALLOWED = new Set([
  "*", // box-sizing: border-box, the same value preflight sets
]);

/** The shadcn parts on #/dev/kit must look the same with the whole `legacy` layer deleted from the page. */
async function kitNotPolluted(ctx) {
  const states = [
    ["closed", async () => {}],
    ["dialog open", async (page) => { await page.locator('[data-kit="dialog-trigger"]').click(); await page.locator('[data-slot="dialog-content"]').waitFor(); }],
    ["menu open", async (page) => { await page.locator('[data-kit="menu-trigger"]').click(); await page.locator('[data-slot="dropdown-menu-content"]').waitFor(); }],
    ["select open", async (page) => { await page.locator('[data-kit="select-trigger"]').click(); await page.locator('[data-slot="select-content"]').waitFor(); }],
    ["tooltip open", async (page) => { await page.locator('[data-kit="tooltip-trigger"]').focus(); await page.locator('[data-slot="tooltip-content"]').first().waitFor(); }],
  ];
  const problems = [];
  let parts = 0, props = 0;
  const inheritedSeen = new Map();
  const matched = new Map();
  for (const theme of ["light", "dark"]) {
    for (const [state, open] of states) {
      const view = await newView(ctx.browser, { width: 1440, theme, label: `kit-${state}`, unmatched });
      try {
        const { page } = view;
        await page.goto(`${ctx.server.url}#/dev/kit`, { waitUntil: "load" });
        await waitReady(page, PAGES.find((p) => p.name === "dev-kit"));
        await settle(page);
        await open(page);
        await settle(page, { pinTranscript: false });
        const result = await page.evaluate(() => {
          // Custom properties are definitions, not styling; every value a component really uses shows up in a normal property.
          const snapshot = (elements) => elements.map((el) => { const cs = getComputedStyle(el); const o = {}; for (const name of cs) if (!name.startsWith("--")) o[name] = cs.getPropertyValue(name); return o; });
          const parts = [...document.querySelectorAll("[data-slot], [data-slot] *")];
          const parents = parts.map((el) => el.parentElement);
          const slotOf = (el) => el.getAttribute("data-slot") ?? `${el.tagName.toLowerCase()} in ${el.closest("[data-slot]").getAttribute("data-slot")}`;
          const label = (el, i) => `${slotOf(el)}#${i}`;
          const roots = [document.body, document.documentElement];
          const before = snapshot(parts), parentsBefore = snapshot(parents), rootsBefore = snapshot(roots);
          // Selector scan: every style rule inside the legacy layer whose selector matches a shadcn part.  This also catches
          // a rule that sets the same value the part would inherit anyway, which the computed-style comparison cannot see.
          const matches = {};
          const scan = (rules) => {
            for (const rule of rules) {
              if (rule.cssRules && !(rule instanceof CSSStyleRule)) { scan(rule.cssRules); continue; }
              if (!(rule instanceof CSSStyleRule) || rule.style.length === 0) continue;
              const hit = new Set();
              try { parts.forEach((el) => { if (el.matches(rule.selectorText)) hit.add(slotOf(el)); }); } catch { /* pseudo-element or unsupported selector */ }
              if (hit.size) matches[`${rule.selectorText} { ${[...rule.style].filter((n) => !n.startsWith("--")).join(", ") || "(custom properties only)"} }`] = [...hit].join(",");
            }
          };
          for (const sheet of document.styleSheets) for (const rule of sheet.cssRules) if (rule instanceof CSSLayerBlockRule && rule.name === "legacy") scan(rule.cssRules);
          let removed = 0;
          for (const sheet of document.styleSheets) {
            for (let i = sheet.cssRules.length - 1; i >= 0; i--) {
              const rule = sheet.cssRules[i];
              if (rule instanceof CSSLayerBlockRule && rule.name === "legacy") { sheet.deleteRule(i); removed += 1; }
            }
          }
          const after = snapshot(parts), parentsAfter = snapshot(parents), rootsAfter = snapshot(roots);
          // A difference is a leak unless the part merely inherits it: same value as its parent both before and after
          // (text defaults the old sheets set on <html>/<body>, e.g. font-family).  Those are listed, not failed.
          const diffs = [], inherited = {};
          parts.forEach((el, i) => {
            for (const name of Object.keys(before[i])) {
              if (before[i][name] === after[i][name]) continue;
              // Resolved currentColor (stroke, outline-color ...): a copy of `color`, which is checked on its own line.
              if (name !== "color" && before[i][name] === before[i].color && after[i][name] === after[i].color) continue;
              if (before[i][name] === parentsBefore[i][name] && after[i][name] === parentsAfter[i][name]) { inherited[name] = (inherited[name] ?? 0) + 1; continue; }
              diffs.push(`${label(el, i)} ${name}: ${before[i][name]} -> ${after[i][name]}`);
            }
          });
          const control = roots.map((_, i) => Object.keys(rootsBefore[i]).filter((name) => rootsBefore[i][name] !== rootsAfter[i][name]).length).reduce((a, b) => a + b, 0);
          return { removed, matches, count: parts.length, slots: [...new Set(parts.map((el) => el.getAttribute("data-slot")).filter(Boolean))], diffs, inherited, control, nprops: Object.keys(before[0] ?? {}).length };
        });
        assert(result.removed >= 1, `${theme}/${state}: no @layer legacy block found to remove`);
        assert(result.control > 0, `${theme}/${state}: removing the legacy layer changed nothing on <body>/<html>, so the check proves nothing`);
        assert(result.count > 0, `${theme}/${state}: no [data-slot] elements on the page`);
        parts += result.count; props += result.count * result.nprops;
        for (const slot of ["button", "input", "checkbox", "switch", "select-trigger"]) assert(result.slots.includes(slot), `${theme}/${state}: missing shadcn part ${slot}`);
        if (state === "dialog open") assert(result.slots.includes("dialog-content"), "dialog content missing");
        if (state === "menu open") assert(result.slots.includes("dropdown-menu-content"), "menu content missing");
        if (state === "select open") assert(result.slots.includes("select-content"), "select content missing");
        if (state === "tooltip open") assert(result.slots.includes("tooltip-content"), "tooltip content missing");
        for (const [name, n] of Object.entries(result.inherited)) inheritedSeen.set(name, (inheritedSeen.get(name) ?? 0) + n);
        for (const line of result.diffs) problems.push(`[${theme}/${state}] ${line}`);
        for (const [rule, slots] of Object.entries(result.matches)) if (!SELECTOR_MATCH_ALLOWED.has(rule.replace(/\{.*$/, "").trim())) matched.set(rule, slots);
      } finally { await view.close(); }
    }
  }
  if (matched.size) { for (const [rule, slots] of matched) problems.push(`legacy rule matches a shadcn part: ${rule}   <- ${slots}`); }
  if (problems.length) { for (const line of problems.slice(0, Number(process.env.SMOKE_DIFF_LINES ?? 60))) console.log(`      ${line}`); throw new Error(`${problems.length} computed-style differences with the legacy layer removed`); }
  const inheritedNote = [...inheritedSeen.keys()].sort().join(", ");
  return `${parts} part snapshots (light+dark, 5 states), ${props} property values compared, ${SELECTOR_MATCH_ALLOWED.size} allowlisted selector(s); only inherited from <html>/<body>, not leaks: ${inheritedNote || "none"}`;
}

/** Keyboard only: the dev-kit overlays open from the keyboard, Esc closes them and focus returns to the trigger. */
async function kitKeyboard(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "kit-keyboard", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit`, { waitUntil: "load" });
    await waitReady(page, PAGES.find((p) => p.name === "dev-kit"));
    await settle(page);
    const focusedKit = () => page.evaluate(() => document.activeElement?.getAttribute("data-kit"));
    const cases = [["dialog-trigger", "dialog-content", "Enter"], ["menu-trigger", "dropdown-menu-content", "Enter"], ["select-trigger", "select-content", "Space"]];
    for (const [trigger, content, key] of cases) {
      await page.locator(`[data-kit="${trigger}"]`).focus();
      assert((await focusedKit()) === trigger, `${trigger}: could not take focus`);
      const ring = await page.evaluate(() => getComputedStyle(document.activeElement).boxShadow);
      assert(ring && ring !== "none", `${trigger}: no visible focus ring on keyboard focus (box-shadow: ${ring})`);
      await page.keyboard.press(key);
      await page.locator(`[data-slot="${content}"]`).waitFor({ timeout: 5000 });
      await page.keyboard.press("Escape");
      await page.locator(`[data-slot="${content}"]`).waitFor({ state: "detached", timeout: 5000 });
      await page.waitForFunction((name) => document.activeElement?.getAttribute("data-kit") === name, trigger, { timeout: 3000 }).catch(() => {});
      assert((await focusedKit()) === trigger, `${trigger}: focus did not return to the trigger after Esc (now ${await focusedKit()})`);
    }
    return "dialog, menu, select: keyboard open, Esc close, focus returns to trigger, focus ring visible";
  } finally { await view.close(); }
}

/**
 * Where the old-browser-default restore applies.  #/dev/kit/probe has the same bare tags twice:
 *  - "outside": no data-legacy above them -> plain preflight (margins 0, no list markers, bare button, inherited link colour ...);
 *  - "island": a data-legacy subtree inside a data-slot container (the P2 shell case) -> browser defaults, as the old pages had.
 */
async function legacyScope(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "kit-scope", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/probe`, { waitUntil: "load" });
    await page.locator('[data-probe="island"]').waitFor({ timeout: 10000 });
    await settle(page, { pinTranscript: false });
    const read = (which) => page.evaluate((name) => {
      const root = document.querySelector(`[data-probe="${name}"]`);
      const get = (tag) => { const el = root.querySelector(tag); const cs = getComputedStyle(el); const parent = getComputedStyle(el.parentElement); return { cs, parent }; };
      const out = {};
      let x = get("h2"); out.h2 = { marginBottom: x.cs.marginBottom, fontSize: x.cs.fontSize, parentFontSize: x.parent.fontSize, fontWeight: x.cs.fontWeight, parentFontWeight: x.parent.fontWeight };
      x = get("p"); out.p = { marginBottom: x.cs.marginBottom };
      x = get("ul"); out.ul = { listStyleType: x.cs.listStyleType, paddingLeft: x.cs.paddingLeft, marginTop: x.cs.marginTop };
      x = get("button"); out.button = { borderTopWidth: x.cs.borderTopWidth, backgroundColor: x.cs.backgroundColor, cursor: x.cs.cursor, paddingTop: x.cs.paddingTop };
      x = get("a"); out.a = { color: x.cs.color, parentColor: x.parent.color, textDecorationLine: x.cs.textDecorationLine };
      x = get("svg"); out.svg = { display: x.cs.display };
      return out;
    }, which);
    const bad = [];
    const expect = (label, ok, got) => { if (!ok) bad.push(`${label}  (got ${JSON.stringify(got)})`); };
    const o = await read("outside"), i = await read("island");
    expect("outside <h2> margin-bottom is 0", o.h2.marginBottom === "0px", o.h2.marginBottom);
    expect("outside <h2> inherits font-size", o.h2.fontSize === o.h2.parentFontSize, [o.h2.fontSize, o.h2.parentFontSize]);
    expect("outside <h2> inherits font-weight", o.h2.fontWeight === o.h2.parentFontWeight, [o.h2.fontWeight, o.h2.parentFontWeight]);
    expect("outside <p> margin-bottom is 0", o.p.marginBottom === "0px", o.p.marginBottom);
    expect("outside <ul> has no list marker", o.ul.listStyleType === "none", o.ul.listStyleType);
    expect("outside <ul> has no padding or margin", o.ul.paddingLeft === "0px" && o.ul.marginTop === "0px", o.ul);
    expect("outside <button> has no border, no padding and a transparent background", o.button.borderTopWidth === "0px" && o.button.paddingTop === "0px" && o.button.backgroundColor === "rgba(0, 0, 0, 0)", o.button);
    expect("outside <button> does not get the old cursor:pointer", o.button.cursor !== "pointer", o.button.cursor);
    expect("outside <a> inherits colour and has no underline", o.a.color === o.a.parentColor && o.a.textDecorationLine === "none", o.a);
    expect("outside <svg> is display:block", o.svg.display === "block", o.svg.display);
    expect("island <h2> has the browser margin", parseFloat(i.h2.marginBottom) > 0, i.h2.marginBottom);
    expect("island <h2> is larger than its parent and heavier (the old sheet sets weight 500, the browser 700)", parseFloat(i.h2.fontSize) > parseFloat(i.h2.parentFontSize) && Number(i.h2.fontWeight) > Number(i.h2.parentFontWeight), i.h2);
    expect("island <p> has the browser margin", parseFloat(i.p.marginBottom) > 0, i.p.marginBottom);
    expect("island <ul> has bullets and indent", i.ul.listStyleType === "disc" && parseFloat(i.ul.paddingLeft) > 0, i.ul);
    expect("island <button> has the browser border and background", parseFloat(i.button.borderTopWidth) > 0 && i.button.backgroundColor !== "rgba(0, 0, 0, 0)", i.button);
    expect("island <button> has the old cursor:pointer", i.button.cursor === "pointer", i.button.cursor);
    expect("island <a> is the browser link blue and underlined", i.a.color === "rgb(0, 0, 238)" && i.a.textDecorationLine === "underline", i.a);
    expect("island <svg> is inline", i.svg.display === "inline", i.svg.display);
    if (bad.length) throw new Error(bad.join("\n"));
    return "outside the marker: plain preflight; marker inside a data-slot container: browser defaults restored";
  } finally { await view.close(); }
}

/**
 * Idle sidebar avatars must not drive a frame loop.  A real-motion view (no reduced-motion preference) opens the
 * portfolio page, which has no live avatar; every bot is idle (unread cleared in the fixture), the pointer rests
 * away from the rail.  window.requestAnimationFrame is wrapped to count calls: still -> ~0, hovering a row -> the
 * loop runs, leaving it (after the gaze has settled) -> ~0 again.  Before the fix a still page costs ~60 calls/s.
 */
async function idleAvatarsNoRaf(ctx) {
  const state = buildState();
  for (const bot of state.bots) { bot.unread = 0; bot.pending = 0; }
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "idle-avatars", unmatched, motion: true, fixtureState: state });
  try {
    const { page } = view;
    await view.context.addInitScript(() => {
      window.__rafCalls = 0;
      const raw = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (callback) => { window.__rafCalls += 1; return raw(callback); };
    });
    await page.goto(`${ctx.server.url}#portfolio`, { waitUntil: "load" });
    await waitReady(page, PAGES.find((p) => p.name === "portfolio"));
    await settle(page);
    await page.locator("[data-bot-row]").first().waitFor({ state: "visible", timeout: 10000 });
    assert((await page.locator("[data-bot-row] .bloub-avatar").count()) >= 5, "expected at least 5 bloub avatars in the sidebar");
    const rafOver = async (ms) => { const before = await page.evaluate(() => window.__rafCalls); await page.waitForTimeout(ms); return (await page.evaluate(() => window.__rafCalls)) - before; };
    const bad = [], seen = {};
    await page.mouse.move(1100, 500);
    await page.waitForTimeout(1000);
    seen.still = await rafOver(3000);
    if (seen.still > 5) bad.push(`still page: ${seen.still} requestAnimationFrame calls in 3 s (limit 5)`);
    const row = page.locator("[data-bot-row]:has(.bloub-avatar)").nth(1);
    await row.hover();
    const box = await row.boundingBox();
    await page.mouse.move(box.x + box.width * 0.4, box.y + box.height / 2); await page.waitForTimeout(150);
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height / 2 + 2);
    seen.hover = await rafOver(1000);
    if (seen.hover < 20) bad.push(`hovering a bot row: only ${seen.hover} calls in 1 s, the eye-follow loop is not running`);
    await page.mouse.move(1100, 500);
    seen.release = await rafOver(500); // the eyes ease back from the pointer: the loop must not stop the instant the pointer leaves
    if (seen.release < 10) bad.push(`right after leaving the row: only ${seen.release} calls in 0.5 s, the gaze release was cut short`);
    await page.waitForTimeout(1500);
    seen.after = await rafOver(2000);
    if (seen.after > 5) bad.push(`after leaving the row and 2 s of settling: ${seen.after} calls in 2 s (limit 5)`);
    if (bad.length) throw new Error(bad.join("\n"));

    // P2.2 (design 6.2, size S): an unread bot does not run frames either.  Its mark is the number badge, drawn in CSS: the
    // avatar stays a still frame.  (Before, an unread bot kept the engine's notify animation: that was the P2.1 check here.)
    const unread = await newView(ctx.browser, { width: 1440, theme: "light", label: "unread-avatar", unmatched, motion: true });
    try {
      await unread.context.addInitScript(() => {
        window.__rafCalls = 0;
        const raw = window.requestAnimationFrame.bind(window);
        window.requestAnimationFrame = (callback) => { window.__rafCalls += 1; return raw(callback); };
      });
      await unread.page.goto(`${ctx.server.url}#portfolio`, { waitUntil: "load" });
      await waitReady(unread.page, PAGES.find((p) => p.name === "portfolio"));
      await settle(unread.page);
      await unread.page.mouse.move(1100, 500);
      await unread.page.waitForTimeout(1500);
      assert((await unread.page.locator('[data-bot-row][data-marker="unread"] [data-count]').count()) >= 1, "the fixture's unread bot shows its number");
      const before = await unread.page.evaluate(() => window.__rafCalls);
      await unread.page.waitForTimeout(2000);
      seen.notify = (await unread.page.evaluate(() => window.__rafCalls)) - before;
    } finally { await unread.close(); }
    assert(seen.notify <= 5, `an unread bot's avatar must not run a frame loop, got ${seen.notify} calls in 2 s`);
    return `still ${seen.still}/3 s, hover ${seen.hover}/1 s, leaving ${seen.release}/0.5 s then settled ${seen.after}/2 s; unread bot ${seen.notify}/2 s`;
  } finally { await view.close(); }
}

/** Colour of an element, as the browser resolves it for `prop`. */
const colorOf = (page, selector, prop = "color") => page.evaluate(([sel, name]) => getComputedStyle(document.querySelector(sel))[name], [selector, prop]);

async function updownSwitchesMarketOnly(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "updown-kit", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit`, { waitUntil: "load" });
    await page.locator('[data-kit="updown-toggle"]').waitFor({ timeout: 10000 });
    await settle(page, { pinTranscript: false });
    // Probe the old sheets too: throw-away elements carrying the old classes, read the same way.
    const legacyProbe = () => page.evaluate(() => {
      const make = (html) => { const host = document.createElement("div"); host.setAttribute("data-legacy", ""); host.setAttribute("data-smoke-probe", ""); host.innerHTML = html; document.body.appendChild(host); return host; };
      const host = make('<span class="delta-up">+1</span><span class="delta-down">-1</span><p class="inventory-error">x</p><div class="action-notice error">x</div><div class="meter"><i class="bearish" style="display:block;width:4px;height:4px"></i></div>');
      const q = (sel) => host.querySelector(sel);
      const out = {
        legacyUp: getComputedStyle(q(".delta-up")).color, legacyDown: getComputedStyle(q(".delta-down")).color,
        legacyError: getComputedStyle(q(".inventory-error")).color, legacyNotice: getComputedStyle(q(".action-notice.error")).borderTopColor,
        legacyBearish: getComputedStyle(q(".meter .bearish")).backgroundColor,
      };
      host.remove();
      return out;
    });
    const read = async () => ({
      attr: await page.evaluate(() => document.documentElement.dataset.updown),
      up: await colorOf(page, '[data-kit-delta="up"]'), down: await colorOf(page, '[data-kit-delta="down"]'),
      success: await colorOf(page, '[data-kit-status="success"]'), danger: await colorOf(page, '[data-kit-status="error"]'),
      barUp: await colorOf(page, '[data-segment="up"]', "backgroundColor"), barDown: await colorOf(page, '[data-segment="down"]', "backgroundColor"),
      ...(await legacyProbe()),
    });
    const before = await read();
    assert(before.attr === "green-up", `default data-updown should be green-up, got ${before.attr}`);
    assert(before.up !== before.down, "up and down must differ");
    assert(before.success === before.up && before.danger === before.down, "by default success is the up colour and danger the down colour");
    assert(before.legacyUp === before.up && before.legacyDown === before.down, `old .delta-up / .delta-down follow --up / --down: ${JSON.stringify(before)}`);
    assert(before.legacyError === before.danger && before.legacyNotice === before.danger, "old error rules use the danger colour");
    assert(before.legacyBearish === before.down, "the old probability bar's bearish segment is the down colour");
    await page.locator('[data-kit="updown-toggle"]').click();
    await page.waitForFunction(() => document.documentElement.dataset.updown === "red-up", null, { timeout: 5000 });
    const after = await read();
    const bad = [];
    const expect = (label, ok, got) => { if (!ok) bad.push(`${label}  (got ${JSON.stringify(got)})`); };
    expect("up number takes the old down colour", after.up === before.down, [after.up, before.down]);
    expect("down number takes the old up colour", after.down === before.up, [after.down, before.up]);
    expect("probability bar segments swap", after.barUp === before.barDown && after.barDown === before.barUp, [after.barUp, after.barDown]);
    expect("success message keeps its colour", after.success === before.success, [after.success, before.success]);
    expect("error message keeps its colour", after.danger === before.danger, [after.danger, before.danger]);
    expect("old .delta-up / .delta-down swap with the market", after.legacyUp === before.legacyDown && after.legacyDown === before.legacyUp, after);
    expect("old error rules keep their colour", after.legacyError === before.legacyError && after.legacyNotice === before.legacyNotice, after);
    expect("old bearish segment follows the down token", after.legacyBearish === after.down, [after.legacyBearish, after.down]);
    // Dark mode swaps the same way (the highest-specificity rule is the dark + red-up one).
    await page.evaluate(() => { document.documentElement.dataset.theme = "dark"; });
    const dark = await read();
    expect("dark red-up: up is red, down is green (not the light values)", dark.up !== after.up && dark.up !== dark.down, [dark.up, after.up]);
    await page.locator('[data-kit="updown-toggle"]').click();
    await page.waitForFunction(() => document.documentElement.dataset.updown === "green-up", null, { timeout: 5000 });
    const darkBack = await read();
    expect("dark green-up: the swap is its mirror image", darkBack.up === dark.down && darkBack.down === dark.up, [darkBack.up, dark.down]);
    expect("dark: success / error colours still fixed", darkBack.success === dark.success && darkBack.danger === dark.danger, [darkBack.success, dark.success]);
    if (bad.length) throw new Error(bad.join("\n"));
    return `up ${before.up} <-> ${before.down}; success ${before.success} and error ${before.danger} stay put; old sheets follow`;
  } finally { await view.close(); }
}

async function updownSettingPersists(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "updown-setting", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/settings/appearance`, { waitUntil: "load" });
    await page.locator("#updown").waitFor({ timeout: 10000 });
    const attr = () => page.evaluate(() => document.documentElement.dataset.updown);
    assert((await attr()) === "green-up", `expected green-up at start, got ${await attr()}`);
    // Focus the trigger and open it from the keyboard (Enter), then pick the second item.
    await page.locator("#updown").focus();
    await page.keyboard.press("Enter");
    await page.getByRole("option", { name: "红涨绿跌" }).waitFor({ timeout: 5000 });
    await page.getByRole("option", { name: "红涨绿跌" }).click();
    await page.waitForFunction(() => document.documentElement.dataset.updown === "red-up", null, { timeout: 5000 });
    const stored = await page.evaluate(() => localStorage.getItem("market-evidence-agent:updown:v1"));
    assert(stored === "red-up", `localStorage should hold red-up, got ${stored}`);
    await page.reload({ waitUntil: "load" });
    await page.locator("#updown").waitFor({ timeout: 10000 });
    assert((await attr()) === "red-up", `after reload expected red-up, got ${await attr()}`);
    const shown = (await page.locator("#updown").innerText()).trim();
    assert(shown === "红涨绿跌", `the control should show the stored choice, got "${shown}"`);
    return "pick red-up -> data-updown=red-up, saved, still red-up after reload, control shows it";
  } finally { await view.close(); }
}

/** name -> check.  Add new checks by writing a function above and registering it here. */
export // --- P2.1: routes ------------------------------------------------------------------------------------------
const UUID_RE = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const FILING = MATERIALS.find((m) => m.symbol === "AAPL" && m.source_type === "official_filing");
// The address readers only accept hex ids for ?revise= and ?focus= (as the old code did); the fixtures' material ids are not hex, so link addresses use this one.
const HEX_ID = "6f1c2d3e-0000-4000-8000-0000000000aa";
const SELECTED_SYMBOL_KEY = "market-evidence-agent:selected-symbol:v1";
const hashOf = (page) => page.evaluate(() => location.hash);
const waitHash = (page, hash, timeout = 10000) => page.waitForFunction((h) => location.hash === h, hash, { timeout });
const dispatchAction = (page, detail) => page.evaluate((d) => window.dispatchEvent(new CustomEvent("market-evidence-agent:client-action", { detail: { id: "a0000000-0000-4000-8000-000000000001", ...d } })), detail);

/** A fresh view; `lastSymbol` seeds the stored "last stock" preference the old-address table reads. */
async function openAt(ctx, label, hash, { lastSymbol = "AAPL", width = 1440, ready, identity } = {}) {
  const view = await newView(ctx.browser, { width, theme: "light", label, unmatched, ...(identity ? { identity } : {}) });
  if (lastSymbol) await view.context.addInitScript(([key, value]) => { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } }, [SELECTED_SYMBOL_KEY, lastSymbol]);
  await view.page.goto(`${ctx.server.url}${hash}`, { waitUntil: "load" });
  if (ready) await waitReady(view.page, { ready });
  return view;
}


/** One old address per kind of the design's table (3.3), opened as a fresh page load: it lands on the new address and the page is ready. */
async function legacyRedirects(ctx) {
  const material = HEX_ID;
  const cases = [
    ["", "#/chat", ".agent-thread .agent-message"],
    ["#agent", "#/chat", ".agent-thread .agent-message"],
    ["#chat", "#/chat", ".agent-thread .agent-message"],
    [`#agent/${CONVERSATION.older}`, `#/chat/c/${CONVERSATION.older}`, ".agent-thread .agent-message"],
    [`#bot/${BOT.applebot}`, `#/chat/${BOT.applebot}`, ".agent-thread .agent-message"],
    ["#overview", "#/research/c/AAPL", ".overview-workspace"],
    ["#company", "#/research/c/AAPL", ".overview-workspace"],
    ["#forecast", "#/research/forecasts", ".forecast-home"],
    ["#forecast?symbol=TSLA", "#/research/forecasts?symbol=TSLA", ".forecast-home"],
    [`#forecast/${ROOT.aapl}`, `#/research/forecasts/${ROOT.aapl}`, ".research-brief"],
    [`#forecast/${ROOT.aapl}?version=${VERSION.aapl2}`, `#/research/forecasts/${ROOT.aapl}?version=${VERSION.aapl2}`, ".research-brief"],
    [`#forecast/${ROOT.aapl}?revise=${material}`, `#/research/forecasts/${ROOT.aapl}?revise=${material}`, ".research-brief"],
    [`#forecast/judgment/${JUDGMENT.aapl}`, `#/research/judgments/${JUDGMENT.aapl}`, ".judgment-page h2"],
    ["#forecast/monitor", "#/research/monitor", "main.workspace .v2-desk h2"],
    ["#revisions", `#/research/forecasts/${ROOT.aapl}?section=versions`, ".research-brief"],
    ["#evaluation", "#/research/scores", "main.workspace h2"],
    ["#replay", "#/research/replay", ".historical-replay-workspace"],
    ["#materials", "#/research/materials", ".material-library-panel h2"],
    ["#library", "#/research/materials", ".material-library-panel h2"],
    [`#materials?symbol=AAPL&focus=${material}&type=official_filing`, `#/research/materials?symbol=AAPL&focus=${material}&type=official_filing`, "!.material-library-panel"],
    ["#evidence", "#/research/evidence?symbol=AAPL", ".evidence-center"],
    [`#evidence/${VERSION.aapl3}`, `#/research/evidence/${VERSION.aapl3}`, ".evidence-center"],
    ["#routines", "#/routines", "main.personal-page h1"],
    ["#briefs", "#/routines", "main.personal-page h1"],
    ["#portfolio", "#/portfolio", ".pf-positions"],
    ["#news", "#/assistant/news", "main.personal-page h1"],
    ["#skills", "#/assistant/skills", ".skill-group"],
    ["#memory", "#/assistant/memory", "main.personal-page h1"],
    ["#me", "#/assistant/bots", "main.personal-page h1"],
    ["#admin", "#/settings/models", ".agent-admin h2"],
    ["#settings", "#/settings/models", ".agent-admin h2"],
    ["#nonsense", "#/chat", ".agent-thread .agent-message"],
    ["#/no/such/page", "#/chat", ".agent-thread .agent-message"],
  ];
  const bad = [];
  for (const [from, to, ready] of cases) {
    const view = await openAt(ctx, `legacy ${from || "(empty)"}`, from);
    try {
      await waitHash(view.page, to, 8000);
      // "!selector": only wait for the element (a focus the fixtures cannot resolve leaves the library's lookup text up).
      if (ready.startsWith("!")) await view.page.waitForSelector(ready.slice(1), { state: "visible", timeout: 15000 });
      else await waitReady(view.page, { ready });
      if (view.problems.pageErrors.length) bad.push(`${from || "(empty)"}: uncaught exception ${view.problems.pageErrors[0].split("\n")[0]}`);
    } catch (error) { bad.push(`${from || "(empty)"} -> expected ${to}, at ${await hashOf(view.page).catch(() => "?")}: ${String(error.message).split("\n")[0]}`); }
    await view.close();
  }
  // The same jump while the app runs (a link in an old answer, a bookmark): replaced, not pushed, so back skips the old form.
  const runtime = await openAt(ctx, "legacy at runtime", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    await settle(runtime.page);
    for (const [from, to] of [["#forecast", "#/research/forecasts"], [`#materials?symbol=AAPL&focus=${HEX_ID}&type=official_filing`, `#/research/materials?symbol=AAPL&focus=${HEX_ID}&type=official_filing`], [`#evidence/${VERSION.aapl3}/official_filing/${FILING.source_id}`, `#/research/evidence/${VERSION.aapl3}/official_filing/${FILING.source_id}`]]) {
      await runtime.page.evaluate(() => { location.hash = "#/chat"; });
      await waitHash(runtime.page, "#/chat");
      await runtime.page.evaluate((h) => { location.hash = h; }, from);
      await waitHash(runtime.page, to);
      await runtime.page.goBack();
      await waitHash(runtime.page, "#/chat");
    }
  } catch (error) { bad.push(`at runtime: ${String(error.message).split("\n")[0]}`); }
  await runtime.close();
  assert(!bad.length, bad.join("\n      "));
  return `${cases.length} old addresses at load + 3 at runtime`;
}

/** chat -> research -> a company -> one of its forecasts -> portfolio, then back four times: every press lands on the previous address. */
async function backButtonChain(ctx) {
  const view = await openAt(ctx, "back chain", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    const trail = [await hashOf(page)];
    const step = async (act, ready) => { await act(); await page.waitForFunction((last) => location.hash !== last, trail.at(-1), { timeout: 10000 }); await waitReady(page, { ready }); trail.push(await hashOf(page)); };
    await step(() => page.evaluate(() => { location.hash = "#/research"; }), ".overview-workspace");
    await step(() => page.locator(".universe-card", { hasText: "AAPL" }).locator("button.universe-open").click(), ".overview-workspace");
    await step(() => page.locator(".overview-focus-actions .primary-action").click(), ".research-brief");
    await step(() => pressNavItem(page, "持仓"), ".pf-positions");
    assert(trail.join(" ") === `#/chat #/research #/research/c/AAPL #/research/forecasts/${ROOT.aapl} #/portfolio`, `unexpected trail ${trail.join(" ")}`);
    const ready = [".research-brief", ".overview-workspace", ".overview-workspace", ".agent-thread .agent-message"];
    for (let i = trail.length - 2; i >= 0; i -= 1) {
      await page.goBack();
      await waitHash(page, trail[i]);
      await waitReady(page, { ready: ready[trail.length - 2 - i] });
    }
    return trail.join(" <- ");
  } finally { await view.close(); }
}

/** The company is in the address: open one, reload, still that company (also with a tab, and on a page that has no company of its own). */
async function deepLinkReload(ctx) {
  const view = await openAt(ctx, "deep link", "#/research/c/TSLA", { lastSymbol: null, ready: ".overview-workspace" });
  try {
    const { page } = view;
    const company = () => page.locator('[data-slot="research-bar"] [role="combobox"]').first().innerText();
    assert((await company()) === "TSLA", `expected TSLA, got ${await company()}`);
    await page.reload({ waitUntil: "load" });
    await waitReady(page, { ready: ".overview-workspace" });
    assert((await hashOf(page)) === "#/research/c/TSLA" && (await company()) === "TSLA", `after reload: ${await hashOf(page)} / ${await company()}`);
    await page.evaluate(() => { location.hash = "#/research/c/NVDA?tab=materials"; });
    await waitReady(page, { ready: ".material-library-panel h2" });
    await page.reload({ waitUntil: "load" });
    await waitReady(page, { ready: ".material-library-panel h2" });
    assert((await hashOf(page)) === "#/research/c/NVDA?tab=materials", `tab lost on reload: ${await hashOf(page)}`);
    assert((await page.locator(".material-library-panel").innerText()).includes("NVDA") || (await company()) === "NVDA", "the library is not about NVDA");
    // The picker switches the company on the same kind of page, through the address.
    await page.locator('[data-slot="research-bar"] [role="combobox"]').click();
    await page.getByRole("option", { name: "AMD" }).click();
    await waitHash(page, "#/research/c/AMD?tab=materials");
    return "TSLA overview and NVDA materials survive a reload; the picker moves the address";
  } finally { await view.close(); }
}

/** The agent's open_page / select_stock / queue events, as the chat page's answers raise them. */
async function clientActions(ctx) {
  const view = await openAt(ctx, "client actions", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    const expected = [
      ["overview", "#/research/c/AAPL"], ["predictions", "#/research/forecasts"], ["materials", "#/research/materials"], ["sec", "#/research/evidence?symbol=AAPL"],
      ["revisions", `#/research/forecasts/${ROOT.aapl}?section=versions`], ["evaluation", "#/research/scores"], ["knowledge", "#/settings/models"], ["agent", "#/chat"],
    ];
    for (const [pageName, hash] of expected) {
      await dispatchAction(page, { action: "open_page", page: pageName });
      await waitHash(page, hash);
    }
    await dispatchAction(page, { action: "open_page", page: "overview" });
    await waitHash(page, "#/research/c/AAPL");
    await waitReady(page, { ready: ".overview-workspace" });
    await dispatchAction(page, { action: "select_stock", symbol: "TSLA" });
    await waitHash(page, "#/research/c/TSLA");
    await dispatchAction(page, { action: "open_page", page: "materials" });
    await waitHash(page, "#/research/materials");
    await dispatchAction(page, { action: "select_stock", symbol: "NVDA" });
    await waitHash(page, "#/research/materials?symbol=NVDA");
    await dispatchAction(page, { action: "open_page", page: "overview" });
    await waitHash(page, "#/research/c/NVDA");
    await waitReady(page, { ready: ".overview-workspace" });
    await dispatchAction(page, { action: "queue_add", symbol: "NFLX" });
    await page.locator(".universe-card", { hasText: "NFLX" }).waitFor({ timeout: 5000 });
    await dispatchAction(page, { action: "queue_remove", symbol: "NFLX" });
    await page.locator(".universe-card", { hasText: "NFLX" }).waitFor({ state: "detached", timeout: 5000 });
    return "open_page x9, select_stock x2, queue_add / queue_remove";
  } finally { await view.close(); }
}

/** Send in a bot's line, leave for another page at once, come back: the session is above the router outlet, so the answer is there. */
async function backgroundTurnSurvivesNavigation(ctx) {
  const view = await openAt(ctx, "background turn", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    await settle(page);
    const text = "导航途中的提问 AAPL";
    await page.locator("#agent-draft").fill(text);
    await page.locator("button.agent-send").click();
    await pressNavItem(page, "持仓");
    await waitHash(page, "#/portfolio");
    await waitReady(page, { ready: ".pf-positions" });
    await pressBotRow(page, "FinBot");
    await waitHash(page, "#/chat");
    await page.locator(".agent-message.is-user", { hasText: text }).waitFor({ timeout: 10000 });
    await page.locator(".agent-message.is-assistant", { hasText: FAKE_ANSWER }).last().waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    return "question sent, left for #/portfolio at once, back: the question and the streamed answer are in the line";
  } finally { await view.close(); }
}


/** A link in a past answer is a plain anchor with an old-form href: clicking it lands on the new route, and back returns to the chat. */
async function answerLinks(ctx) {
  const view = await openAt(ctx, "answer links", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    const links = [
      [`#materials?symbol=AAPL&focus=${HEX_ID}&type=official_filing`, `#/research/materials?symbol=AAPL&focus=${HEX_ID}&type=official_filing`],
      [`#forecast/${ROOT.aapl}?version=${VERSION.aapl2}`, `#/research/forecasts/${ROOT.aapl}?version=${VERSION.aapl2}`],
      [`#agent/${CONVERSATION.older}`, `#/chat/c/${CONVERSATION.older}`],
      [`#evidence/${VERSION.aapl3}/official_filing/${FILING.source_id}`, `#/research/evidence/${VERSION.aapl3}/official_filing/${FILING.source_id}`],
    ];
    for (const [href, to] of links) {
      await page.evaluate((h) => { const a = document.createElement("a"); a.id = "probe-link"; a.href = h; a.textContent = "link"; a.style.cssText = "position:fixed;top:0;left:0;z-index:99999;background:#fff"; document.body.appendChild(a); }, href);
      await page.locator("#probe-link").click();
      await waitHash(page, to);
      await page.evaluate(() => document.getElementById("probe-link")?.remove());
      await page.goBack();
      await waitHash(page, "#/chat");
    }
    return `${links.length} old-form anchors clicked, each opens the new route and back returns to #/chat`;
  } finally { await view.close(); }
}

/** A page whose chunk cannot be fetched (offline, or removed by a new deploy) shows the load-failure notice inside the shell, and reload recovers. */
async function chunkLoadFailure(ctx) {
  const view = await openAt(ctx, "chunk failure", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    await settle(page);
    let blocked = true;
    await view.context.route(/\/assets\/forecast-[^/]*\.js$/, (route) => (blocked ? route.abort() : route.continue()));
    await page.evaluate((id) => { location.hash = `#/research/forecasts/${id}`; }, ROOT.aapl);
    await page.locator('[data-slot="route-error"]').waitFor({ timeout: 10000 });
    const text = await page.locator('[data-slot="route-error"]').innerText();
    assert(text.includes("页面加载失败") && text.includes("重新加载"), `unexpected notice: ${text}`);
    assert(await page.locator('[data-slot="sidebar"]').count() > 0, "the shell is gone");
    blocked = false;
    await page.locator('[data-slot="route-error"] button').click();
    await page.waitForLoadState("load");
    await waitReady(page, { ready: ".research-brief" });
    return "forecast chunk aborted: notice with reload inside the shell; after reload the forecast opens";
  } finally { await view.close(); }
}

/**
 * No class the built `utilities` layer defines may also be a class the old UI uses (see collisions.mjs): Tailwind turns
 * words in src/app, src/components and src/dev (comments included) into utility rules, and that layer beats `legacy`.
 * Reads the build output and the sources next to it (<dist>/../src); no browser.
 */
async function utilityLegacyCollisions() {
  const result = findCollisions({ distDir: path.resolve(flags.dist), srcDir: path.resolve(flags.dist, "..", "src") });
  assert(!result.collisions.length, `utility classes that also name old classes: ${result.collisions.join(", ")}.  Find the word in src/app, src/components or src/dev (comments and strings count) and reword it, or move the code out of the scanned folders; allow it in collisions.mjs only with a reason.`);
  return `${result.utilities.size} utility classes vs ${result.legacy.size} old class names (${result.oldTsx} old tsx files + legacy css): none shared${result.allowed.length ? ` except the allowed ${result.allowed.join(", ")}` : ""}`;
}

// --- P2.2: the shell -----------------------------------------------------------------------------------------------
const SIDEBAR_KEY = "market-evidence-agent:sidebar-open:v1";
const MODE_KEY = "market-evidence-agent:chat-mode:v1";
/** A view at `hash`, as the personal owner (default), a guest or nobody. */
async function openShell(ctx, label, hash, { width = 1440, identity = "personal", theme = "light", ready } = {}) {
  const view = await newView(ctx.browser, { width, theme, label, unmatched, identity });
  await view.page.goto(`${ctx.server.url}${hash}`, { waitUntil: "load" });
  if (ready) await waitReady(view.page, { ready });
  return view;
}
const sidebarState = (page) => page.evaluate(() => document.querySelector('[data-slot="sidebar"]')?.getAttribute("data-state") ?? null);
const sidebarWidth = (page) => page.evaluate(() => Math.round(document.querySelector('[data-slot="sidebar-container"]')?.getBoundingClientRect().width ?? -1));

/** Every page, at 390 wide: nothing makes the document wider than the window. */
async function noHorizontalScroll390(ctx) {
  const bad = [];
  for (const def of PAGES) {
    const view = await newView(ctx.browser, { width: 390, theme: "light", identity: def.identity ?? "personal", label: `h-scroll ${def.name}`, unmatched });
    try {
      await view.page.goto(`${ctx.server.url}${def.hash ?? ""}`, { waitUntil: "load" });
      await waitReady(view.page, def);
      await settle(view.page);
      const sizes = await view.page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth, body: document.body.scrollWidth }));
      if (sizes.scroll > sizes.inner) {
        const wide = await view.page.evaluate(() => [...document.querySelectorAll("body *")].filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1).slice(0, 3).map((el) => `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]}`));
        bad.push(`${def.name}: scrollWidth ${sizes.scroll} > ${sizes.inner} (${wide.join(", ")})`);
      }
    } catch (error) { bad.push(`${def.name}: ${String(error.message).split("\n")[0]}`); }
    await view.close();
  }
  assert(!bad.length, bad.join("\n      "));
  return `${PAGES.length} pages, none wider than 390`;
}

/** The collapse button folds the sidebar to 56px; a reload keeps the choice, in either direction. */
async function sidebarCollapsePersists(ctx) {
  const view = await openShell(ctx, "sidebar collapse", "#/portfolio", { ready: ".pf-positions" });
  try {
    const { page } = view;
    await settle(page);
    assert((await sidebarState(page)) === "expanded" && (await sidebarWidth(page)) === 260, `expected 260px expanded at start, got ${await sidebarState(page)} / ${await sidebarWidth(page)}`);
    await page.locator('[data-slot="sidebar-trigger"]').click();
    await page.waitForFunction(() => document.querySelector('[data-slot="sidebar"]')?.getAttribute("data-state") === "collapsed");
    assert((await page.evaluate((key) => localStorage.getItem(key), SIDEBAR_KEY)) === "0", "the choice is not stored");
    await page.reload({ waitUntil: "load" });
    await waitReady(page, { ready: ".pf-positions" });
    await settle(page);
    assert((await sidebarState(page)) === "collapsed" && (await sidebarWidth(page)) === 56, `after a reload: ${await sidebarState(page)} / ${await sidebarWidth(page)}`);
    // Collapsed, a group with sub-pages is one icon whose menu lists them (the expanded sidebar lists them inline).
    await page.locator('[data-slot="sidebar"] button[aria-label="研究"]').click();
    const menu = page.getByRole("menu");
    await menu.waitFor({ timeout: 10000 });
    const listed = await menu.getByRole("menuitem").allInnerTexts();
    assert(["自选", "预测", "材料库", "证据", "模型成绩", "历史回放"].every((name) => listed.includes(name)), `the collapsed 研究 menu lists: ${listed.join(", ")}`);
    await page.keyboard.press("Escape");
    await menu.waitFor({ state: "detached", timeout: 5000 });
    await page.locator('[data-slot="sidebar-trigger"]').click();
    await page.waitForFunction(() => document.querySelector('[data-slot="sidebar"]')?.getAttribute("data-state") === "expanded");
    await page.reload({ waitUntil: "load" });
    await waitReady(page, { ready: ".pf-positions" });
    assert((await sidebarState(page)) === "expanded", "expanding was not kept either");
    return "260px -> 56px, reload, still 56px; collapsed 研究 icon opens its menu; back to 260px, reload, still 260px";
  } finally { await view.close(); }
}

/** The 任务 number is the live proposals plus the open write suggestions, and the 任务 page lists exactly that many waiting cards. */
async function routinesBadgeMatches(ctx) {
  const expected = PROPOSALS.filter((p) => !p.expired).length + INBOX.filter((i) => i.section === "confirm" && i.status !== "done" && i.status !== "dismissed").length;
  const view = await openShell(ctx, "routines badge", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    const badge = page.locator('[data-slot="sidebar"] a[href="#/routines"]').locator("xpath=..").locator("[data-count]");
    await badge.waitFor({ timeout: 10000 });
    const shown = Number((await badge.innerText()).trim());
    assert(shown === expected, `sidebar shows ${shown}, the fixtures hold ${expected}`);
    // No bot row repeats a task number: ReportBot has a pending item and no unread count.
    const reportRow = page.locator("[data-bot-row]", { hasText: "ReportBot" });
    assert((await reportRow.locator("[data-count]").count()) === 0, "a bot row prints a number for its pending task items");
    // The page: live proposals + suggestions waiting.
    await pressNavItem(page, "任务");
    await waitHash(page, "#/routines");
    await waitReady(page, { ready: "main.personal-page h1" });
    await page.locator("#routine-confirms-title").waitFor({ timeout: 10000 });
    const proposals = await page.locator("#routine-proposals-title").locator("xpath=..").locator("li").filter({ hasNotText: "已过期" }).count();
    const confirms = await page.locator("#routine-confirms-title").locator("xpath=..").locator("ul.memory-list > li").count();
    assert(proposals + confirms === shown, `the page lists ${proposals} proposals + ${confirms} suggestions, the badge says ${shown}`);
    // The phone's bar carries the same number.
    const phone = await openShell(ctx, "routines badge phone", "#/portfolio", { width: 390, ready: ".pf-positions" });
    try {
      const phoneBadge = phone.page.locator('[data-slot="mobile-tab-bar"] a[href="#/routines"] [data-count]');
      await phoneBadge.waitFor({ timeout: 10000 });
      assert(Number((await phoneBadge.innerText()).trim()) === shown, "the tab bar's 任务 number differs from the sidebar's");
    } finally { await phone.close(); }
    return `badge ${shown} = ${proposals} proposals + ${confirms} suggestions on the page; same on the phone's bar; no number on the bot rows`;
  } finally { await view.close(); }
}

/** Mode switch and sign-out exist once, in the account menu; the chat header, settings and the other pages have neither. */
async function modeSwitchSingleEntry(ctx) {
  const names = /切换模式|切换到访客只读|登出|登录个人/;
  const view = await openShell(ctx, "mode switch", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    await settle(page);
    const count = (role) => page.getByRole(role, { name: names }).count();
    assert((await count("button")) + (await count("menuitem")) + (await count("link")) === 0, "a mode / sign-out control is on the page before the menu is open");
    assert((await page.getByText("个人模式", { exact: true }).count()) === 1, "the mode label should appear once (the account menu)");
    assert((await page.getByRole("button", { name: "切换模式" }).count()) === 0 && (await page.getByRole("button", { name: "设置", exact: true }).count()) === 0, "the chat header still has 切换模式 / 设置");
    const trigger = page.locator('[data-slot="sidebar-footer"] button[aria-haspopup="menu"]');
    assert((await trigger.count()) === 1, "expected exactly one account menu trigger");
    await trigger.click();
    await page.getByRole("menuitem", { name: "切换到访客只读" }).waitFor();
    assert((await page.getByRole("menuitem", { name: "登出" }).count()) === 1 && (await page.getByRole("menuitem", { name: "登录个人" }).count()) === 0, "personal menu: expected 切换到访客只读 + 登出 only");
    for (const hash of ["#/settings/models", "#/research", "#/assistant/memory"]) {
      await page.keyboard.press("Escape");
      await page.evaluate((h) => { location.hash = h; }, hash);
      await page.waitForFunction((h) => location.hash === h, hash);
      await settle(page, { pinTranscript: false });
      assert((await page.getByRole("button", { name: /切换模式/ }).count()) === 0, `${hash} has a 切换模式 button`);
    }
    // Switch to guest through the menu, then the menu offers the login instead.
    await trigger.click();
    await page.getByRole("menuitem", { name: "切换到访客只读" }).click();
    await page.locator('[data-slot="guest-composer"]').waitFor({ timeout: 10000 });
    assert((await page.evaluate((key) => localStorage.getItem(key), MODE_KEY)) === "guest", "mode is not guest");
    await trigger.click();
    await page.getByRole("menuitem", { name: "登录个人" }).waitFor();
    assert((await page.getByRole("menuitem", { name: "切换到访客只读" }).count()) === 0, "guest menu still offers the switch to guest");
    // Sign out: back to the login page, no mode stored.
    await page.getByRole("menuitem", { name: "登出" }).click();
    await page.locator('[aria-labelledby="login-title"]').waitFor({ timeout: 10000 });
    assert((await page.evaluate((key) => localStorage.getItem(key), MODE_KEY)) === null, "the chosen mode survives a sign-out");
    return "one trigger; personal menu = 切换到访客只读 + 登出; guest menu = 登录个人 + 登出; none on chat / settings / research / memory; sign-out reaches the login page";
  } finally { await view.close(); }
}

/** First visit: the login page at #/login; a wrong code reads its error under the field; the right one lands on the page asked for, or on the chat. */
async function loginFlow(ctx) {
  const deep = await openShell(ctx, "login deep link", "#/research/forecasts", { identity: "none" });
  try {
    const { page } = deep;
    await page.locator('[aria-labelledby="login-title"]').waitFor({ timeout: 10000 });
    assert((await hashOf(page)) === "#/research/forecasts", `a deep link must stay, got ${await hashOf(page)}`);
    const field = page.locator('input[type="password"]');
    await field.fill("not-the-code");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    const error = page.locator("#login-error");
    await error.waitFor({ timeout: 10000 });
    const below = await page.evaluate(() => { const input = document.querySelector('input[type="password"]').getBoundingClientRect(), err = document.getElementById("login-error").getBoundingClientRect(); return err.top >= input.bottom - 1; });
    assert(below, "the error is not under the field");
    assert((await field.getAttribute("aria-invalid")) === "true", "the field is not marked invalid");
    await field.fill(LOGIN_CODE);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await waitReady(page, { ready: ".forecast-home" });
    assert((await hashOf(page)) === "#/research/forecasts", `login lost the page: ${await hashOf(page)}`);
    assert((await page.locator('[data-slot="sidebar"] [data-bot-row]').count()) >= 5, "the shell shows no bots after the login");
  } finally { await deep.close(); }
  const first = await openShell(ctx, "login first open", "", { identity: "none" });
  try {
    const { page } = first;
    await page.locator('[aria-labelledby="login-title"]').waitFor({ timeout: 10000 });
    await waitHash(page, "#/login");
    await page.locator('input[type="password"]').fill(LOGIN_CODE);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await waitHash(page, "#/chat");
    await waitReady(page, { ready: ".agent-thread .agent-message" });
  } finally { await first.close(); }
  const again = await openShell(ctx, "login while signed in", "#/login", { ready: ".agent-thread .agent-message" });
  try { await waitHash(again.page, "#/chat"); } finally { await again.close(); }
  const guest = await openShell(ctx, "login read-only", "#/login", { identity: "none" });
  try {
    await guest.page.locator('[aria-labelledby="login-title"]').waitFor({ timeout: 10000 });
    await guest.page.getByRole("button", { name: "只读浏览" }).click();
    await waitHash(guest.page, "#/chat");
    await guest.page.locator('[data-slot="guest-composer"]').waitFor({ timeout: 10000 });
  } finally { await guest.close(); }
  return "deep link kept through a wrong code (error under the field) and the right one; bare address -> #/login -> #/chat; signed in at #/login -> #/chat; 只读浏览 -> #/chat as a guest";
}

/** Browsing read-only: research pages open, the chat's input area is the sign-in notice, the owner's pages say 需要登录, the sidebar offers no bots. */
async function guestReadonly(ctx) {
  const view = await openShell(ctx, "guest", "#/chat", { identity: "guest", ready: '[data-slot="guest-composer"]' });
  try {
    const { page } = view;
    const notice = await page.locator('[data-slot="guest-composer"]').innerText();
    assert(notice.includes("登录后可以对话") && (await page.locator('[data-slot="guest-composer"] button', { hasText: "登录" }).count()) === 1, `unexpected notice: ${notice}`);
    assert((await page.locator("#agent-draft").count()) === 0 && (await page.locator("button.agent-send").count()) === 0, "a guest still has an input box and a send button");
    assert((await page.getByText("继续访客聊天").count()) === 0, "the dead 继续访客聊天 path is still around");
    assert((await page.locator("[data-bot-row]").count()) === 0, "a guest sees bots");
    assert((await page.locator('[data-slot="sidebar"] a[href="#/portfolio"], [data-slot="sidebar"] a[href="#/routines"]').count()) === 0, "a guest's sidebar lists 持仓 / 任务");
    await page.locator('[data-slot="guest-composer"] button', { hasText: "登录" }).click();
    await page.getByRole("dialog").waitFor({ timeout: 5000 });
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached", timeout: 5000 });
    // What a guest can read: the research pages.
    for (const [hash, ready] of [["#/research/forecasts", ".forecast-home"], ["#/research/materials", ".material-library-panel h2"], ["#/research/replay", ".historical-replay-workspace"], ["#/settings/appearance", "select#theme"]]) {
      await page.evaluate((h) => { location.hash = h; }, hash);
      await waitReady(page, { ready });
    }
    // What the owner alone can use: one plain notice and a way in.
    for (const hash of ["#/portfolio", "#/routines", "#/assistant/memory", "#/assistant/news", `#/chat/${BOT.applebot}`]) {
      await page.evaluate((h) => { location.hash = h; }, hash);
      await page.locator('[data-slot="need-login"]').waitFor({ timeout: 10000 });
      const text = await page.locator('[data-slot="need-login"]').innerText();
      assert(text.includes("需要登录") && (await page.locator('[data-slot="need-login"] button', { hasText: "登录" }).count()) === 1, `${hash}: unexpected notice ${text}`);
      assert((await page.locator('[role="alert"]').count()) === 0, `${hash}: an error bar is showing`);
    }
    return "chat input = 登录后可以对话 + 登录; 4 read-only pages open; 5 owner pages show 需要登录 + 登录; no bots, no 持仓 / 任务 entries";
  } finally { await view.close(); }
}

/** Keyboard only: Tab reaches every sidebar entry and Enter follows it; the login dialog closes on Esc and gives focus back. */
async function keyboardNav(ctx) {
  const view = await openShell(ctx, "keyboard nav", "#/research", { ready: ".overview-workspace" });
  try {
    const { page } = view;
    await settle(page);
    const expected = await page.locator('[data-slot="sidebar"] a[href]').evaluateAll((els) => els.map((el) => el.getAttribute("href")));
    assert(expected.length >= 15, `expected 15+ sidebar links, found ${expected.length}`);
    await page.locator('[data-slot="sidebar"] a[href]').first().focus();
    const seen = new Set();
    for (let i = 0; i < 80 && seen.size < expected.length; i += 1) {
      const href = await page.evaluate(() => { const el = document.activeElement; return el?.closest('[data-slot="sidebar"]') && el.getAttribute("href"); });
      if (href) seen.add(href);
      await page.keyboard.press("Tab");
    }
    const missed = expected.filter((href) => !seen.has(href));
    assert(!missed.length, `Tab never reached: ${missed.join(", ")}`);
    // Focus is visible on a sidebar link.
    await page.locator('[data-slot="sidebar"] a[href="#/portfolio"]').focus();
    const ring = await page.evaluate(() => getComputedStyle(document.activeElement).boxShadow);
    assert(ring && ring !== "none", `no visible focus ring on a sidebar link (box-shadow ${ring})`);
    // Enter follows a link; a bot row too.
    await page.keyboard.press("Enter");
    await waitHash(page, "#/portfolio");
    await page.locator("[data-bot-row]", { hasText: "NewsBot" }).focus();
    await page.keyboard.press("Enter");
    await waitHash(page, `#/chat/${BOT.newsbot}`);
    // The login dialog: opens on the refused-write event, Esc closes it, focus is back on the control that had it.
    const anchor = page.locator('[data-slot="sidebar"] a[href="#/routines"]');
    await anchor.focus();
    await page.evaluate(() => window.dispatchEvent(new Event("owner-auth-required")));
    await page.getByRole("dialog").waitFor({ timeout: 5000 });
    assert((await page.evaluate(() => document.activeElement?.getAttribute("type"))) === "password", "focus did not go into the dialog's field");
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached", timeout: 5000 });
    await page.waitForFunction(() => document.activeElement?.getAttribute("href") === "#/routines", null, { timeout: 3000 });
    // The account menu opens from the keyboard and Esc gives focus back to its button.
    const account = page.locator('[data-slot="sidebar-footer"] button[aria-haspopup="menu"]');
    await account.focus();
    await page.keyboard.press("Enter");
    await page.getByRole("menu").waitFor({ timeout: 5000 });
    await page.keyboard.press("Escape");
    await page.getByRole("menu").waitFor({ state: "detached", timeout: 5000 });
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-haspopup") === "menu", null, { timeout: 3000 });
    return `${expected.length} sidebar links all reached by Tab, focus ring visible, Enter navigates (page + bot row); dialog and menu close on Esc and return focus`;
  } finally { await view.close(); }
}

/** The phone: five items in the bar (each 44+ px), no sidebar in the page, and 更多 holds the bots, 助手, 设置, the account and the theme switch. */
async function mobileBarAndMore(ctx) {
  const view = await openShell(ctx, "mobile bar", "#/chat", { width: 390, ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    await settle(page);
    assert((await page.locator('[data-slot="sidebar"]').count()) === 0, "the sidebar is in the page on a phone");
    const items = await page.locator('[data-slot="mobile-tab-bar"] > a, [data-slot="mobile-tab-bar"] > button').evaluateAll((els) => els.map((el) => ({ name: el.innerText.trim().split("\n").pop(), w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height, current: el.getAttribute("aria-current") })));
    assert(items.map((i) => i.name).join("|") === "对话|研究|持仓|任务|更多", `bar items: ${items.map((i) => i.name).join("|")}`);
    for (const item of items) assert(item.w >= 44 && item.h >= 44, `${item.name}: ${Math.round(item.w)}x${Math.round(item.h)} is under 44x44`);
    assert(items[0].current === "page", "the current tab is not marked");
    const bottom = await page.evaluate(() => { const bar = document.querySelector('[data-slot="mobile-tab-bar"]').getBoundingClientRect(); return { gap: window.innerHeight - bar.bottom, padding: getComputedStyle(document.querySelector('[data-slot="mobile-tab-bar"]')).paddingBottom }; });
    assert(Math.abs(bottom.gap) <= 1, `the bar is not at the bottom edge (gap ${bottom.gap})`);
    await page.locator('[data-slot="mobile-tab-bar"] button', { hasText: "更多" }).click();
    const drawer = page.locator('[data-slot="drawer-content"]');
    await drawer.waitFor({ timeout: 10000 });
    const text = await drawer.innerText();
    const wanted = ["FinBot", "AppleBot", "NewsBot", "ReportBot", "TeslaBot", "历史对话", "新建 bot", "全部 bot", "技能", "记忆", "新闻源", "知识库", "模型", "通知", "外观", "数据", "账户", "切换到访客只读", "登出"];
    const missing = wanted.filter((word) => !text.includes(word));
    assert(!missing.length, `更多 lacks: ${missing.join(", ")}`);
    assert((await drawer.getByRole("button", { name: /切换到(深色|浅色)/ }).count()) === 1, "no light / dark switch in 更多");
    // Another bot is reachable from the phone: through the drawer.
    await drawer.getByRole("link", { name: "NewsBot" }).click();
    await waitHash(page, `#/chat/${BOT.newsbot}`);
    await page.locator('[data-slot="drawer-content"]').waitFor({ state: "detached", timeout: 5000 });
    return `5 bar items >= 44x44 at the bottom edge; 更多 lists ${wanted.length} entries incl. the bots; NewsBot opened from it`;
  } finally { await view.close(); }
}

/** The old-UI restore still works inside the new shell: bare tags on three old pages keep the browser's margins; the sidebar's tags do not. */
async function legacyRestoreInShell(ctx) {
  const view = await openShell(ctx, "restore in shell", "#/settings/models", { ready: ".agent-admin h2" });
  try {
    const { page } = view;
    const bad = [];
    for (const [hash, ready] of [["#/settings/models", ".agent-admin h2"], ["#/assistant/skills", ".skill-group"], ["#/assistant/memory", "main.personal-page h1"]]) {
      await page.evaluate((h) => { location.hash = h; }, hash);
      await waitReady(page, { ready });
      await settle(page, { pinTranscript: false });
      const read = await page.evaluate(() => {
        // A tag of an old page, not inside a shadcn part that sits within the marker (those keep preflight by design).
        const inPage = (tag) => [...document.querySelectorAll(`[data-legacy] ${tag}`)].find((el) => { const slot = el.closest("[data-slot]"); return !slot || !el.closest("[data-legacy]").contains(slot); });
        const margin = (el) => (el ? parseFloat(getComputedStyle(el).marginBottom) : null);
        return { h2: margin(inPage("h2")), p: margin(inPage("p")), marker: Boolean(document.querySelector("[data-legacy]")), insideSidebar: Boolean(document.querySelector('[data-slot="sidebar"]')?.closest("[data-legacy]")) };
      });
      if (!read.marker) bad.push(`${hash}: no data-legacy marker`);
      if (read.insideSidebar) bad.push(`${hash}: the sidebar is inside the old-UI marker`);
      if (!(read.h2 > 0) && !(read.p > 0)) bad.push(`${hash}: bare <h2>/<p> margins are ${read.h2}/${read.p}; the browser default should be back`);
    }
    const sidebar = await page.evaluate(() => {
      const root = document.querySelector('[data-slot="sidebar"]');
      const ul = root.querySelector("ul"), a = root.querySelector("a"), button = root.querySelector('[data-slot="sidebar-trigger"]'), p = root.querySelector("p");
      const cs = (el) => (el ? getComputedStyle(el) : null);
      return { listStyle: cs(ul).listStyleType, padLeft: cs(ul).paddingLeft, marginTop: cs(ul).marginTop, underline: cs(a).textDecorationLine, linkColour: cs(a).color, parentColour: cs(a.parentElement).color, border: cs(button).borderTopWidth, pMargin: p ? cs(p).marginBottom : "0px" };
    });
    if (sidebar.listStyle !== "none" || sidebar.padLeft !== "0px" || sidebar.marginTop !== "0px") bad.push(`sidebar <ul> is restored: ${JSON.stringify(sidebar)}`);
    if (sidebar.underline !== "none") bad.push(`sidebar <a> underlined`);
    if (sidebar.border !== "0px") bad.push(`sidebar <button> has a browser border`);
    if (sidebar.pMargin !== "0px") bad.push(`sidebar <p> has a margin`);
    assert(!bad.length, bad.join("\n      "));
    return "3 old pages: browser margins back on bare <h2>/<p>; the sidebar's <ul>/<a>/<button>/<p> are plain preflight";
  } finally { await view.close(); }
}

/** The four marks of a bot row are told apart: ring (answering), amber dot (waiting), number (unread), nothing. */
async function botRowMarks(ctx) {
  const view = await openShell(ctx, "bot marks", "#/chat", { ready: ".agent-thread .agent-message" });
  try {
    const { page } = view;
    await settle(page);
    // The fixture: NewsBot has 2 unread, ReportBot waits on an item; hold an answer in TeslaBot's line for the fourth.
    await page.evaluate((id) => { location.hash = `#/chat/${id}`; }, BOT.teslabot);
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await page.locator("#agent-draft").fill("[hold-the-answer] AAPL");
    await page.locator("button.agent-send").click();
    await page.locator("button.agent-stop").waitFor({ timeout: 10000 });
    await page.evaluate(() => { location.hash = "#/chat"; });
    await page.locator('[data-bot-row][data-marker="running"]').waitFor({ timeout: 10000 });
    const row = (name) => page.locator("[data-bot-row]", { hasText: name });
    const kinds = {};
    for (const name of ["TeslaBot", "ReportBot", "NewsBot", "AppleBot"]) kinds[name] = await row(name).getAttribute("data-marker");
    assert(JSON.stringify(kinds) === JSON.stringify({ TeslaBot: "running", ReportBot: "waiting", NewsBot: "unread", AppleBot: "none" }), `marks: ${JSON.stringify(kinds)}`);
    assert((await row("TeslaBot").locator("[data-ring]").count()) === 1 && (await row("TeslaBot").locator("[data-dot]").count()) === 0, "answering: one ring, no dot");
    assert((await row("ReportBot").locator("[data-dot]").count()) === 1 && (await row("ReportBot").locator("[data-ring]").count()) === 0 && (await row("ReportBot").locator("[data-count]").count()) === 0, "waiting: one dot, no ring, no number");
    assert((await row("NewsBot").locator("[data-count]").innerText()).trim() === "2" && (await row("NewsBot").locator("[data-dot], [data-ring]").count()) === 0, "unread: the number only");
    assert((await row("AppleBot").locator("[data-dot], [data-ring], [data-count]").count()) === 0, "quiet: no mark");
    const dot = await row("ReportBot").locator("[data-dot]").evaluate((el) => getComputedStyle(el).backgroundColor);
    const action = await page.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--action)"; document.body.appendChild(probe); const colour = getComputedStyle(probe).color; probe.remove(); return colour; });
    assert(dot === action, `the waiting dot is ${dot}, the action colour is ${action}`);
    return "TeslaBot = ring, ReportBot = amber dot, NewsBot = number 2, AppleBot = none; the dot is the action colour";
  } finally { await view.close(); }
}

const CHECKS = [
  ["every page opens and reaches its ready condition", everyPageOpens],
  ["send a message: user line, streamed answer, composer reusable", sendMessageStreams],
  ["switch to another bot and back: URL changes, earlier answer kept", switchBotAndBack],
  ["browser back returns to the previous address", backButtonReturns],
  ["theme toggle flips data-theme on <html>", themeToggles],
  ["legacy-redirects: old #addresses land on their new route (load and runtime), pages ready", legacyRedirects],
  ["back-button-chain: chat > research > company > forecast > portfolio, four backs", backButtonChain],
  ["deep-link-reload: the company in the address survives a reload; the picker moves the address", deepLinkReload],
  ["client-actions: open_page, select_stock, queue events move the address", clientActions],
  ["utility-legacy-collisions: no utility class defined by the build is also an old class name", utilityLegacyCollisions],
  ["answer-links: old-form anchors in past answers open the new routes; back returns", answerLinks],
  ["chunk-load-failure: a page that fails to load shows the notice inside the shell; reload recovers", chunkLoadFailure],
  ["background-turn-survives-navigation: a turn sent before leaving is in the line on return", backgroundTurnSurvivesNavigation],
  ["thinking panel expands to the turn trace", thinkingPanelExpands],
  ["#/dev/kit: shadcn parts are identical with the legacy layer removed", kitNotPolluted],
  ["#/dev/kit: dialog, menu and select work from the keyboard and return focus", kitKeyboard],
  ["#/dev/kit/probe: restore applies only inside data-legacy, preflight everywhere else", legacyScope],
  ["#/dev/kit: the up/down switch swaps market colours only (new and old styles); success and error stay", updownSwitchesMarketOnly],
  ["settings page: the up/down choice changes <html data-updown> and survives a reload", updownSettingPersists],
  ["idle-avatars-no-raf: sidebar avatars (idle or unread) run no frame loop; hover starts it, leaving stops it", idleAvatarsNoRaf],
  ["no-horizontal-scroll-390: every page fits a 390px window", noHorizontalScroll390],
  ["sidebar-collapse-persists: collapse to 56px, reload, still collapsed (and back)", sidebarCollapsePersists],
  ["routines-badge-matches: the 任务 number = live proposals + open suggestions = what the 任务 page lists", routinesBadgeMatches],
  ["mode-switch-single-entry: mode switch and sign-out only in the account menu", modeSwitchSingleEntry],
  ["login-flow: wrong code shows its error under the field, right code returns to the page; first visit, signed-in visit, 只读浏览", loginFlow],
  ["guest-readonly: read-only chat input is the sign-in notice; owner pages say 需要登录; no bots", guestReadonly],
  ["keyboard-nav: Tab reaches every sidebar entry, Enter navigates, dialog and menu close on Esc and return focus", keyboardNav],
  ["mobile-bar-and-more: five 44px items, no sidebar, 更多 lists the bots, 助手, 设置, account, theme", mobileBarAndMore],
  ["legacy-restore-in-shell: old pages keep browser margins inside the new shell; the sidebar's tags are preflight", legacyRestoreInShell],
  ["bot-row-marks: answering / waiting / unread / quiet rows are told apart", botRowMarks],
];

const selected = typeof flags.only === "string" ? CHECKS.filter(([name]) => name.includes(flags.only)) : CHECKS;
if (!selected.length) { console.error(`--only ${flags.only}: no check has that in its name`); process.exit(2); }
const server = await startServer(flags.dist);
const browser = await launch();
let failed = 0;
for (const [name, check] of selected) {
  try { const detail = await check({ browser, server }); console.log(`PASS  ${name}${detail ? `  (${detail})` : ""}`); }
  catch (error) { failed += 1; console.log(`FAIL  ${name}\n      ${String(error?.message ?? error).split("\n").join("\n      ")}`); }
}
await browser.close(); await server.close();

const missing = summarizeUnmatched(unmatched);
if (missing.length) { console.log(`\nunmatched API requests (${missing.length}):`); for (const item of missing) console.log(`  ${item.request}   <- ${item.pages.join(", ")}`); }
else console.log("\nunmatched API requests: none");
console.log(`\n${selected.length - failed} passed, ${failed} failed`);
process.exit(failed || (flags.strict && missing.length) ? 1 : 0);
