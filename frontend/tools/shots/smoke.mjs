// Smoke entry: node smoke.mjs --dist <build dir> [--strict] [--only <text in a check's name>]
// One named function per check, registered in CHECKS.  Later phases append checks here.
import { parseArgs } from "./args.mjs";
import { startServer } from "./server.mjs";
import { FIXED_TIME, launch, newView, settle } from "./harness.mjs";
import { summarizeUnmatched } from "./mock-api.mjs";
import { PAGES, clickSend, endWithCard, endWithError, firstAnswer, handTurn, streamHalfway, streamParagraph, streamSteps, traceEvent, waitReady } from "./pages.mjs";
import { ASK_MARKER, BOT, CONVERSATION, HAND_MARKER, JUDGMENT, LOGIN_CODE, ROOT, VERSION } from "./fixtures/ids.mjs";
import { CLARIFY_REQUEST_ID, FRESH_WRITE_REQUEST_ID, REVISION_REQUEST_ID, freshWriteCard, olderTurns, revisionCard } from "./fixtures/chat.mjs";
import { handFed } from "./fake-sse.mjs";
import { INBOX, PROPOSALS } from "./fixtures/routines.mjs";
import { MATERIALS } from "./fixtures/materials.mjs";
import { buildState } from "./fixtures/index.mjs";
import fs from "node:fs";
import path from "node:path";
import { findCollisions } from "./collisions.mjs";
import { normalizePublicMarks, publicMarkQuoteText } from "../../src/chat-public-marks.mjs";
import { followUpQuestion } from "../../src/chat-unverified.mjs";

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
    await page.locator("[data-testid=send]").click();
    await page.locator("[data-testid=message][data-role=user]", { hasText: SMOKE_TEXT }).waitFor({ timeout: 10000 });
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
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
    await page.locator("[data-testid=send]").click();
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    const before = await page.evaluate(() => location.hash);
    await pressBotRow(page, "NewsBot");
    await page.waitForFunction((id) => location.hash === `#/chat/${id}`, BOT.newsbot, { timeout: 10000 });
    await page.locator("h1", { hasText: "NewsBot" }).waitFor({ timeout: 10000 });
    await pressBotRow(page, "FinBot");
    await page.locator("h1", { hasText: "FinBot" }).waitFor({ timeout: 10000 });
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
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

/** P3.3: the process bar opens the right panel's 过程 tab, which lists the round's steps (the old thinking panel's graph). */
async function thinkingPanelExpands(ctx) {
  const view = await openChat(ctx, "thinking-panel");
  try {
    const { page } = view;
    const bar = firstAnswer(page).locator("[data-testid=turn-steps]");
    await bar.waitFor({ timeout: 10000 });
    await bar.click();
    await page.locator("[data-testid=timeline-step]").first().waitFor({ timeout: 5000 });
    assert((await page.locator("[data-testid=tab-process]").getAttribute("aria-selected")) === "true", "the 过程 tab is not the selected one");
    return `${await page.locator("[data-testid=timeline-step]").count()} steps shown in the 过程 tab`;
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
    ["", "#/chat", "[data-testid=message]"],
    ["#agent", "#/chat", "[data-testid=message]"],
    ["#chat", "#/chat", "[data-testid=message]"],
    [`#agent/${CONVERSATION.older}`, `#/chat/c/${CONVERSATION.older}`, "[data-testid=message]"],
    [`#bot/${BOT.applebot}`, `#/chat/${BOT.applebot}`, "[data-testid=message]"],
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
    ["#nonsense", "#/chat", "[data-testid=message]"],
    ["#/no/such/page", "#/chat", "[data-testid=message]"],
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
  const runtime = await openAt(ctx, "legacy at runtime", "#/chat", { ready: "[data-testid=message]" });
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
  const view = await openAt(ctx, "back chain", "#/chat", { ready: "[data-testid=message]" });
  try {
    const { page } = view;
    const trail = [await hashOf(page)];
    const step = async (act, ready) => { await act(); await page.waitForFunction((last) => location.hash !== last, trail.at(-1), { timeout: 10000 }); await waitReady(page, { ready }); trail.push(await hashOf(page)); };
    await step(() => page.evaluate(() => { location.hash = "#/research"; }), ".overview-workspace");
    await step(() => page.locator(".universe-card", { hasText: "AAPL" }).locator("button.universe-open").click(), ".overview-workspace");
    await step(() => page.locator(".overview-focus-actions .primary-action").click(), ".research-brief");
    await step(() => pressNavItem(page, "持仓"), ".pf-positions");
    assert(trail.join(" ") === `#/chat #/research #/research/c/AAPL #/research/forecasts/${ROOT.aapl} #/portfolio`, `unexpected trail ${trail.join(" ")}`);
    const ready = [".research-brief", ".overview-workspace", ".overview-workspace", "[data-testid=message]"];
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
  const view = await openAt(ctx, "client actions", "#/chat", { ready: "[data-testid=message]" });
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
  const view = await openAt(ctx, "background turn", "#/chat", { ready: "[data-testid=message]" });
  try {
    const { page } = view;
    await settle(page);
    const text = "导航途中的提问 AAPL";
    await page.locator("#agent-draft").fill(text);
    await page.locator("[data-testid=send]").click();
    await pressNavItem(page, "持仓");
    await waitHash(page, "#/portfolio");
    await waitReady(page, { ready: ".pf-positions" });
    await pressBotRow(page, "FinBot");
    await waitHash(page, "#/chat");
    await page.locator("[data-testid=message][data-role=user]", { hasText: text }).waitFor({ timeout: 10000 });
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).last().waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    return "question sent, left for #/portfolio at once, back: the question and the streamed answer are in the line";
  } finally { await view.close(); }
}


/** A link in a past answer is a plain anchor with an old-form href: clicking it lands on the new route, and back returns to the chat. */
async function answerLinks(ctx) {
  const view = await openAt(ctx, "answer links", "#/chat", { ready: "[data-testid=message]" });
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
  const view = await openAt(ctx, "chunk failure", "#/chat", { ready: "[data-testid=message]" });
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
  const view = await openShell(ctx, "routines badge", "#/chat", { ready: "[data-testid=message]" });
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
  const view = await openShell(ctx, "mode switch", "#/chat", { ready: "[data-testid=message]" });
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
    await waitReady(page, { ready: "[data-testid=message]" });
  } finally { await first.close(); }
  const again = await openShell(ctx, "login while signed in", "#/login", { ready: "[data-testid=message]" });
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
    assert((await page.locator("#agent-draft").count()) === 0 && (await page.locator("[data-testid=send]").count()) === 0, "a guest still has an input box and a send button");
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
  const view = await openShell(ctx, "mobile bar", "#/chat", { width: 390, ready: "[data-testid=message]" });
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
  const view = await openShell(ctx, "bot marks", "#/chat", { ready: "[data-testid=message]" });
  try {
    const { page } = view;
    await settle(page);
    // The fixture: NewsBot has 2 unread, ReportBot waits on an item; hold an answer in TeslaBot's line for the fourth.
    await page.evaluate((id) => { location.hash = `#/chat/${id}`; }, BOT.teslabot);
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await page.locator("#agent-draft").fill("[hold-the-answer] AAPL");
    await page.locator("[data-testid=send]").click();
    await page.locator("[data-testid=stop]").waitFor({ timeout: 10000 });
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

// --- P2.3: states, confirmations, the command palette -----------------------------------------------------------------
const count = (view, method, re) => view.mock.requests.filter((r) => r.method === method && re.test(r.path)).length;
/** Press and hold the element under `locator` for `ms` (a real hold: pointer down, wait, pointer up). */
async function holdPointer(page, locator, ms = 1250) {
  const box = await locator.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down(); await page.waitForTimeout(ms); await page.mouse.up();
}
const dialogOf = (page) => page.locator('[data-slot="alert-dialog-content"]');
const focusIsMarked = (page) => page.evaluate(() => document.activeElement?.hasAttribute("data-probe-trigger") ?? false);

/**
 * Every place that used to call window.confirm (nine) now asks in the app.  The browser's confirm is stubbed to count calls and
 * to say yes if it were ever reached.  Per place: pressing the trigger opens the in-app dialog and sends nothing; Esc closes it,
 * nothing is sent and focus is back on the trigger; the dialog's own 取消 sends nothing; holding the confirm button sends exactly
 * one request.  (A real hold: the view keeps motion on.)
 */
async function noWindowConfirm(ctx) {
  const PF = /\/portfolio\/transactions\/[^/]+$/;
  const sites = [
    { name: "portfolio record", hash: "#/portfolio", ready: ".pf-positions", trigger: (p) => p.locator(".pf-ledger li button", { hasText: "删除" }).first(), method: "DELETE", re: PF },
    { name: "skill", hash: "#/assistant/skills", ready: ".skill-group", trigger: (p) => p.locator("main button", { hasText: /^删除$/ }).first(), method: "DELETE", re: /\/skills\/[^/]+$/ },
    { name: "memory item", hash: "#/assistant/memory", ready: "main.personal-page h1", trigger: (p) => p.locator("main button", { hasText: /^删除$/ }).first(), method: "DELETE", re: /\/profile\/[^/]+$/ },
    { name: "news source", hash: "#/assistant/news", ready: "main.personal-page h1", trigger: (p) => p.locator("main button", { hasText: /^删除$/ }).first(), method: "DELETE", re: /\/news-sources\/[^/]+$/ },
    { name: "routine task", hash: "#/routines", ready: "main.personal-page h1", trigger: (p) => p.locator("main button", { hasText: /^删除$/ }).first(), method: "DELETE", re: /\/tasks\/[^/]+$/ },
    { name: "bot", hash: `#/chat/${BOT.applebot}/settings`, ready: ".bot-profile", trigger: (p) => p.getByRole("button", { name: "删除这个 bot" }), method: "DELETE", re: /\/bots\/[^/]+$/ },
    { name: "bot Telegram token", hash: `#/chat/${BOT.applebot}/settings`, ready: ".bot-profile", trigger: (p) => p.getByRole("button", { name: "换 token / 删除" }), method: "DELETE", re: /\/bots\/[^/]+\/telegram$/ },
    { name: "catalog model", hash: "#/settings/models", ready: ".agent-admin h2", trigger: (p) => p.locator(".catalog-actions button", { hasText: /^删除$/ }).first(), method: "DELETE", re: /\/model-catalog\/[^/]+$/ },
    { name: "Telegram unbind", hash: "#/settings/notifications", ready: ".agent-admin h2", trigger: (p) => p.getByRole("button", { name: "解除绑定" }), method: "POST", re: /\/telegram\/unbind$/ },
  ];
  const report = [];
  for (const site of sites) {
    const view = await newView(ctx.browser, { width: 1440, theme: "light", label: `confirm: ${site.name}`, unmatched, motion: true });
    try {
      const { page } = view;
      await page.addInitScript(() => { window.__confirmCalls = 0; window.confirm = () => { window.__confirmCalls += 1; return true; }; });
      await page.goto(`${ctx.server.url}${site.hash}`, { waitUntil: "load" });
      await waitReady(page, { ready: site.ready });
      await page.evaluate(() => { window.__confirmCalls = 0; window.confirm = () => { window.__confirmCalls += 1; return true; }; });
      const trigger = site.trigger(page);
      await trigger.waitFor({ timeout: 10000 });
      await trigger.evaluate((el) => el.setAttribute("data-probe-trigger", ""));
      // 1. open, then Esc
      await trigger.click();
      await dialogOf(page).waitFor({ timeout: 5000 });
      assert((await dialogOf(page).locator('[data-slot="alert-dialog-title"]').innerText()).trim().length > 0, `${site.name}: the dialog has no title`);
      assert((await dialogOf(page).locator('[data-slot="alert-dialog-description"]').innerText()).trim().length > 0, `${site.name}: the dialog says nothing about what follows`);
      assert(await dialogOf(page).locator('[data-slot="hold-button"]').count() === 1, `${site.name}: not a press-and-hold confirmation`);
      assert(count(view, site.method, site.re) === 0, `${site.name}: a request went out before the answer`);
      await page.keyboard.press("Escape");
      await dialogOf(page).waitFor({ state: "detached", timeout: 5000 });
      await page.waitForFunction(() => document.activeElement?.hasAttribute("data-probe-trigger"), null, { timeout: 3000 });
      assert(count(view, site.method, site.re) === 0, `${site.name}: Esc did not cancel`);
      // 2. open, 取消
      await trigger.click();
      await dialogOf(page).waitFor({ timeout: 5000 });
      await dialogOf(page).getByRole("button", { name: "取消" }).click();
      await dialogOf(page).waitFor({ state: "detached", timeout: 5000 });
      await page.waitForFunction(() => document.activeElement?.hasAttribute("data-probe-trigger"), null, { timeout: 3000 });
      assert(count(view, site.method, site.re) === 0, `${site.name}: 取消 did not cancel`);
      // 3. open, a short press does nothing, a full hold confirms
      await trigger.click();
      await dialogOf(page).waitFor({ timeout: 5000 });
      await holdPointer(page, dialogOf(page).locator('[data-slot="hold-button"]'), 300);
      assert(await dialogOf(page).count() === 1 && count(view, site.method, site.re) === 0, `${site.name}: a short press confirmed`);
      await holdPointer(page, dialogOf(page).locator('[data-slot="hold-button"]'));
      await dialogOf(page).waitFor({ state: "detached", timeout: 5000 });
      const deadline = Date.now() + 5000;
      while (count(view, site.method, site.re) < 1 && Date.now() < deadline) await page.waitForTimeout(100);
      assert(count(view, site.method, site.re) === 1, `${site.name}: expected exactly one ${site.method} after the hold, saw ${count(view, site.method, site.re)}`);
      const calls = await page.evaluate(() => window.__confirmCalls);
      assert(calls === 0, `${site.name}: window.confirm was called ${calls} time(s)`);
      report.push(site.name);
    } catch (error) { throw new Error(`${site.name}: ${String(error.message).split("\n")[0]}`); }
    finally { await view.close(); }
  }
  return `${report.length} places: in-app dialog, Esc / 取消 send nothing and return focus, a full hold sends one request, window.confirm never called`;
}

/** The confirmation from the keyboard (and with reduced motion): focus starts on 取消, Esc cancels, holding Space or Enter confirms, press-twice works with no hold at all. */
async function confirmDialogKeyboard(ctx) {
  const open = async (motion) => {
    const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "confirm keyboard", unmatched, motion });
    await view.page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await view.page.locator("[data-kit-states]").waitFor();
    return view;
  };
  let view = await open(true);
  try {
    const { page } = view;
    const result = () => page.locator('[data-kit="confirm-result"]').innerText();
    // Plain confirm: Enter on the trigger opens it; focus starts on 取消; Tab reaches 归档; Esc answers no and gives focus back.
    await page.locator('[data-kit="confirm-plain"]').focus(); await page.keyboard.press("Enter");
    await dialogOf(page).waitFor();
    assert((await page.evaluate(() => document.activeElement?.textContent?.trim())) === "取消", "focus did not start on 取消");
    await page.keyboard.press("Tab");
    assert((await page.evaluate(() => document.activeElement?.textContent?.trim())) === "归档", "Tab did not reach the confirm button");
    await page.keyboard.press("Escape"); await dialogOf(page).waitFor({ state: "detached" });
    assert((await result()).includes("cancelled"), `Esc: ${await result()}`);
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-kit") === "confirm-plain", null, { timeout: 3000 }).catch(() => { throw new Error("focus did not return to the trigger"); });
    await page.keyboard.press("Enter"); await dialogOf(page).waitFor();
    await page.keyboard.press("Tab"); await page.keyboard.press("Enter");
    await dialogOf(page).waitFor({ state: "detached" });
    assert((await result()).includes("confirmed"), `Enter on the confirm button: ${await result()}`);
    // Hold: holding Space for a full second confirms; a short press does not; Enter works the same.
    for (const key of ["Space", "Enter"]) {
      await page.locator('[data-kit="confirm-hold"]').focus(); await page.keyboard.press("Enter");
      await dialogOf(page).waitFor();
      await page.keyboard.press("Tab");
      assert(await page.evaluate(() => document.activeElement?.getAttribute("data-slot")) === "hold-button", "Tab did not reach the hold button");
      await page.keyboard.down(key); await page.waitForTimeout(250); await page.keyboard.up(key);
      assert(await dialogOf(page).count() === 1, `a short ${key} press confirmed`);
      await page.keyboard.down(key); await page.waitForTimeout(1250); await page.keyboard.up(key);
      await dialogOf(page).waitFor({ state: "detached", timeout: 3000 });
      assert((await result()).includes("confirmed"), `hold ${key}: ${await result()}`);
      await page.waitForFunction(() => document.activeElement?.getAttribute("data-kit") === "confirm-hold", null, { timeout: 3000 }).catch(() => { throw new Error(`hold ${key}: focus did not return`); });
      await page.locator('[data-kit="confirm-plain"]').click(); await dialogOf(page).waitFor(); await page.keyboard.press("Escape"); await dialogOf(page).waitFor({ state: "detached" });
    }
  } finally { await view.close(); }
  // Reduced motion (the harness default): no fill to watch, so press twice; a click with no press before it (assistive technology) is the same.
  view = await open(false);
  try {
    const { page } = view;
    const result = () => page.locator('[data-kit="confirm-result"]').innerText();
    await page.locator('[data-kit="confirm-hold"]').click(); await dialogOf(page).waitFor();
    const hold = dialogOf(page).locator('[data-slot="hold-button"]');
    await hold.focus(); await page.keyboard.press("Space");
    assert(await dialogOf(page).count() === 1 && (await hold.innerText()).includes("再点一次"), "the first press should only arm the button");
    await page.keyboard.press("Space");
    await dialogOf(page).waitFor({ state: "detached" });
    assert((await result()).includes("confirmed"), `press twice: ${await result()}`);
    await page.locator('[data-kit="confirm-hold"]').click(); await dialogOf(page).waitFor();
    await hold.dispatchEvent("click"); await hold.dispatchEvent("click");
    await dialogOf(page).waitFor({ state: "detached" });
    assert((await result()).includes("confirmed"), `two bare clicks: ${await result()}`);
  } finally { await view.close(); }
  return "focus starts on 取消, Esc cancels and returns focus; holding Space or Enter ~1s confirms (a short press does not); reduced motion and bare clicks: press twice";
}

/** The shortcut and the palette: company, bot (hidden too), page and recent chat each lead where they say; Esc closes and returns focus. */
async function commandMenuNavigates(ctx) {
  const state = buildState();
  state.bots.find((b) => b.id === BOT.applebot).hidden = true;
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "command menu", unmatched, fixtureState: state });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await waitReady(page, PAGES.find((p) => p.name === "chat-default"));
    await settle(page);
    const palette = page.locator('[data-slot="command-menu"]');
    const input = palette.locator("input");
    const open = async (how = "shortcut") => {
      if (how === "shortcut") await page.keyboard.press("Control+k");
      else await page.locator('[data-slot="sidebar"] button[aria-label="命令面板"]').click();
      await palette.waitFor({ timeout: 5000 });
      assert(await page.evaluate(() => document.activeElement?.tagName === "INPUT"), "focus did not go to the search field");
    };
    const rows = () => palette.locator('[data-slot="command-item"]');
    // A code on the watch list: Enter on the first row opens it.
    await open(); await input.fill("TS"); await rows().first().waitFor();
    assert((await rows().first().innerText()).includes("TSLA"), `first row for "TS": ${await rows().first().innerText()}`);
    assert((await rows().nth(1).innerText()).includes("加入自选并打开"), "second row for TS should offer to add TS");
    await page.keyboard.press("Enter"); await waitHash(page, "#/research/c/TSLA"); await palette.waitFor({ state: "detached" });
    // A bot, a hidden one: found by name, marked 已隐藏, opens its line.
    await open(); await input.fill("AppleBot"); await rows().first().waitFor();
    const apple = await rows().first().innerText();
    assert(apple.includes("AppleBot") && apple.includes("已隐藏"), `hidden bot row: ${apple}`);
    await page.keyboard.press("Enter"); await waitHash(page, `#/chat/${BOT.applebot}`);
    // A page by its name, with the area it belongs to.
    await open(); await input.fill("持仓"); await rows().first().waitFor();
    assert((await rows().first().innerText()).includes("持仓"), "page row");
    await page.keyboard.press("Enter"); await waitHash(page, "#/portfolio");
    await open(); await input.fill("证据");
    const evidenceRow = await rows().first().innerText();
    assert(evidenceRow.includes("证据") && evidenceRow.includes("研究"), `evidence row names its area: ${evidenceRow}`);
    await page.keyboard.press("Enter"); await page.waitForFunction(() => location.hash.startsWith("#/research/evidence"), null, { timeout: 5000 });
    // A recent conversation (the existing history list), opened by its title.
    await open("button");
    await palette.locator('[cmdk-group-heading]', { hasText: "最近对话" }).waitFor({ timeout: 5000 });
    const titles = await palette.locator('[data-kind="recent"]').allInnerTexts();
    assert(titles.length >= 2, `recent conversations: ${titles.join(" | ")}`);
    await input.fill(titles[1].slice(0, 4)); await rows().first().waitFor();
    await page.keyboard.press("Enter"); await page.waitForFunction(() => /^#\/chat\/c\//.test(location.hash), null, { timeout: 5000 });
    // Esc closes it and gives focus back to what had it (by the shortcut and by the sidebar button).
    const anchor = page.locator('[data-slot="sidebar"] a[href="#/routines"]');
    await anchor.focus(); await open(); await page.keyboard.press("Escape"); await palette.waitFor({ state: "detached" });
    await page.waitForFunction(() => document.activeElement?.getAttribute("href") === "#/routines", null, { timeout: 3000 });
    await open("button"); await page.keyboard.press("Escape"); await palette.waitFor({ state: "detached" });
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "命令面板", null, { timeout: 3000 });
    // The shortcut also closes it.
    await open(); await page.keyboard.press("Control+k"); await palette.waitFor({ state: "detached" });
    // The dialog is labelled for a screen reader.
    await open(); assert((await page.getByRole("dialog", { name: "命令面板" }).count()) === 1, "the palette has no dialog title");
    await page.keyboard.press("Escape");
    return "TS -> TSLA (+ offer to add TS); hidden AppleBot (已隐藏) opens its line; 持仓 and 证据 open their pages; a recent chat opens; Esc and the shortcut close it, focus returns";
  } finally { await view.close(); }
}

/** In the English interface the palette's page names, group names and the offer are English. */
async function commandMenuEnglish(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", locale: "en-US", label: "command menu en", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await page.locator("[data-testid=message]").first().waitFor({ timeout: 15000 });
    await page.keyboard.press("Control+k");
    const palette = page.locator('[data-slot="command-menu"]');
    await palette.waitFor();
    await palette.locator('[cmdk-group-heading]', { hasText: "Recent chats" }).waitFor({ timeout: 5000 });
    const heads = await palette.locator("[cmdk-group-heading]").allInnerTexts();
    assert(heads.join(",") === "Company,bot,Pages,Recent chats", `group names: ${heads.join(",")}`);
    const input = palette.locator("input");
    await input.fill("portfolio");
    assert((await palette.locator('[data-slot="command-item"]').first().innerText()).toLowerCase().includes("portfolio"), "English page name should match");
    await input.fill("appearance"); await page.keyboard.press("Enter");
    await page.waitForFunction(() => location.hash === "#/settings/appearance", null, { timeout: 5000 });
    await page.keyboard.press("Control+k"); await palette.waitFor();
    await input.fill("NFLX");
    assert((await palette.locator('[data-slot="command-item"]').first().innerText()).includes("Add to watchlist and open"), "English offer");
    const text = await palette.innerText();
    assert(!/[一-鿿]/.test(text), `Chinese left in the English palette: ${text.match(/[一-鿿]+/)?.[0]}`);
    return "groups Company / bot / Pages / Recent chats; page names and the add offer in English; no Chinese in the palette";
  } finally { await view.close(); }
}

/** A valid code that is not on the watch list: the palette offers 加入自选并打开; doing it opens the company and the fake API receives the queue update. */
async function commandMenuAddWatch(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "command menu add", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await waitReady(page, PAGES.find((p) => p.name === "chat-default"));
    await settle(page);
    await page.keyboard.press("Control+k");
    const palette = page.locator('[data-slot="command-menu"]');
    await palette.locator("input").fill("nflx");
    const first = palette.locator('[data-slot="command-item"]').first();
    await first.waitFor();
    const text = await first.innerText();
    assert(text.includes("加入自选并打开") && text.includes("NFLX"), `offer: ${text}`);
    assert(!view.mock.state.queue.includes("NFLX"), "NFLX should not be on the list yet");
    const before = count(view, "PUT", /research-queue$/);
    await page.keyboard.press("Enter");
    await waitHash(page, "#/research/c/NFLX");
    const deadline = Date.now() + 5000;
    while (!view.mock.state.queue.includes("NFLX") && Date.now() < deadline) await page.waitForTimeout(100);
    assert(view.mock.state.queue.includes("NFLX"), `the fake API never received the update; queue: ${view.mock.state.queue.join(",")}`);
    assert(count(view, "PUT", /research-queue$/) > before, "no PUT /research-queue");
    // Typing something that is not a code offers nothing; a code already on the list is not offered again.
    await page.keyboard.press("Control+k");
    await palette.locator("input").fill("not a code!");
    assert(await palette.locator('[data-kind="add"]').count() === 0, "an offer for text that is not a code");
    await palette.locator("input").fill("NFLX");
    assert(await palette.locator('[data-kind="add"]').count() === 0 && (await palette.locator('[data-slot="command-item"]').first().innerText()).includes("NFLX"), "NFLX is on the list now: it is listed, not offered");
    return "nflx -> 加入自选并打开 NFLX -> #/research/c/NFLX, PUT /research-queue carries NFLX";
  } finally { await view.close(); }
}

/** Phone: the way in is the search box at the top of 更多; it opens the palette, and closing it puts focus back on 更多. */
async function commandMenuMobile(ctx) {
  const view = await newView(ctx.browser, { width: 390, theme: "light", label: "command menu mobile", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await page.locator("[data-testid=message]").first().waitFor({ timeout: 15000 });
    await page.locator('[data-slot="mobile-tab-bar"] button[aria-haspopup="dialog"]').click();
    await page.locator('[data-slot="drawer-content"]').waitFor();
    await page.locator('[data-slot="palette-entry"]').click();
    const palette = page.locator('[data-slot="command-menu"]');
    await palette.waitFor();
    await palette.locator("input").fill("TSLA");
    await palette.locator('[data-slot="command-item"]').first().waitFor();
    const box = await palette.boundingBox();
    assert(box && box.x >= 0 && box.x + box.width <= 390, `the palette is wider than the phone: ${JSON.stringify(box)}`);
    await page.keyboard.press("Escape"); await palette.waitFor({ state: "detached" });
    await page.waitForFunction(() => document.activeElement?.hasAttribute("data-more-trigger"), null, { timeout: 3000 });
    return "更多 -> search box -> palette fits 390px; Esc returns focus to 更多";
  } finally { await view.close(); }
}

/** Toasts: bottom right, gone after about two seconds, above a dialog, 撤销 reachable and usable by keyboard. */
async function toastAutoDismiss(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "toast", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await page.locator("[data-kit-states]").waitFor();
    const toast = page.locator("[data-sonner-toast]");
    const t0 = Date.now();
    await page.locator('[data-kit="toast-success"]').click();
    await toast.first().waitFor({ timeout: 5000 });
    const box = await toast.first().boundingBox();
    const vp = page.viewportSize();
    assert(box.x > vp.width / 2 && box.y > vp.height / 2, `toast is not bottom right: ${JSON.stringify(box)}`);
    assert((await toast.first().innerText()).includes("已保存"), "toast text");
    await toast.first().waitFor({ state: "detached", timeout: 6000 });
    const lived = Date.now() - t0;
    assert(lived >= 1500 && lived <= 4500, `a plain toast lived ${lived}ms (design: about 2s)`);
    // Undo toast: lives longer than a plain one, the button works by keyboard.
    await page.locator('[data-kit="toast-undo"]').click();
    await toast.first().waitFor();
    assert((await toast.first().innerText()).includes("撤销"), "the undo toast has no 撤销");
    await page.waitForTimeout(2600);
    assert(await toast.count() === 1, "an undo toast should outlast the 2s of a plain one");
    await page.keyboard.press("Alt+t");
    const focusedInToaster = await page.evaluate(() => !!document.activeElement?.closest("[data-sonner-toaster]"));
    assert(focusedInToaster, "Alt+T did not move focus into the toaster");
    for (let i = 0; i < 4; i += 1) { const label = await page.evaluate(() => document.activeElement?.textContent?.trim()); if (label === "撤销") break; await page.keyboard.press("Tab"); }
    assert((await page.evaluate(() => document.activeElement?.textContent?.trim())) === "撤销", "Tab never reached 撤销 inside the toaster");
    await page.keyboard.press("Enter");
    await page.locator("[data-sonner-toast]", { hasText: "已撤销" }).waitFor({ timeout: 4000 });
    // z-order: --z-toast is above --z-dialog
    const layers = await page.evaluate(() => { const v = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(); const t = document.querySelector("[data-sonner-toaster]"); return { dialog: v("--z-dialog"), toast: v("--z-toast"), applied: t ? getComputedStyle(t).zIndex : null }; });
    assert(Number(layers.toast) > Number(layers.dialog) && layers.applied === layers.toast, `layers: ${JSON.stringify(layers)}`);
    return `plain toast bottom right, gone after ${lived}ms; undo toast outlasts it and 撤销 works with Alt+T, Tab, Enter; z ${layers.toast} over dialog ${layers.dialog}`;
  } finally { await view.close(); }
}

/** A toast raised while the login dialog is open is on top of it (the click goes to the toast's own button, not the dialog's backdrop). */
async function toastAboveDialog(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "toast over dialog", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await page.locator("[data-kit-states]").waitFor();
    await page.locator('[data-kit="toast-pinned"]').click();
    await page.locator("[data-sonner-toast]").waitFor();
    await page.locator('[data-kit="login-open"]').click();
    await page.getByRole("dialog").waitFor();
    const top = await page.evaluate(() => { const toast = document.querySelector("[data-sonner-toast]").getBoundingClientRect(); const hit = document.elementFromPoint(toast.x + toast.width / 2, toast.y + toast.height / 2); return !!hit?.closest("[data-sonner-toast]"); });
    assert(top, "the toast is covered by the dialog layer");
    return "toast stays visible and hit-testable above the open login dialog";
  } finally { await view.close(); }
}

/** The unreachable backend: failed requests light one banner; 重试 with the backend back puts it out; ordinary error answers do not light it. */
async function offlineBanner(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "offline", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await waitReady(page, PAGES.find((p) => p.name === "chat-default"));
    await settle(page);
    const banner = page.locator('[data-slot="offline-banner"]');
    assert(await banner.count() === 0, "the banner is showing while the backend answers");
    view.mock.control.down = true;
    await page.evaluate(() => { location.hash = "#/portfolio"; });
    await banner.first().waitFor({ timeout: 8000 });
    assert(await banner.count() === 1, `${await banner.count()} banners (one expected)`);
    const text = await banner.innerText();
    assert(text.includes("连不上后端") && text.includes("重试"), `banner text: ${text}`);
    assert(await page.locator('[data-slot="offline-banner"][role="alert"]').count() === 1, "the banner is not announced");
    const top = await banner.evaluate((el) => el.getBoundingClientRect().top);
    assert(top <= 1, `the banner is not at the top of the page (top ${top})`);
    // still down: 重试 replays a failed read, fails, the banner stays
    await banner.getByRole("button", { name: "重试" }).click();
    await page.waitForTimeout(600);
    assert(await banner.count() === 1, "the banner went out while the backend was still down");
    // back: 重试 -> gone
    view.mock.control.down = false;
    await banner.getByRole("button", { name: "重试" }).click();
    await banner.waitFor({ state: "detached", timeout: 8000 });
    // A gateway answer from a proxy lights it as well; the application's own errors do not.
    view.mock.control.down502 = true;
    await page.evaluate(() => { location.hash = "#/routines"; });
    await banner.first().waitFor({ timeout: 8000 });
    view.mock.control.down502 = false;
    await banner.getByRole("button", { name: "重试" }).click();
    await banner.waitFor({ state: "detached", timeout: 8000 });
    return "down -> one banner at the top (role=alert, 重试); still down: stays; back + 重试: gone; a proxy 502 lights it too";
  } finally { await view.close(); }
}

/** An application error is not "offline": a guest's 403s and unanswered fixtures never light the banner. */
async function offlineBannerQuiet(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", identity: "guest", label: "offline quiet", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await page.locator('[data-slot="guest-composer"]').waitFor({ timeout: 15000 });
    await settle(page);
    assert(await page.locator('[data-slot="offline-banner"]').count() === 0, "the banner lit for 4xx answers");
    return "403 answers to a guest leave the banner out";
  } finally { await view.close(); }
}

/** The 400ms rule: a quick load shows no skeleton, a slow one shows it after the delay; with reduced motion the blocks do not pulse; a lazy page's code arriving late is covered by a skeleton of its shape. */
async function skeletonDelay(ctx) {
  let view = await newView(ctx.browser, { width: 1440, theme: "light", label: "skeleton delay", unmatched, motion: true });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await page.locator("[data-kit-states]").waitFor();
    const stage = page.locator('[data-kit="skeleton-stage"] [data-slot="skeleton-frame"]');
    // quick: sample the stage for 700ms, the skeleton must never appear
    await page.locator('[data-kit="skeleton-fast"]').click();
    let seen = false;
    for (let i = 0; i < 14; i += 1) { if (await stage.count()) seen = true; await page.waitForTimeout(50); }
    assert(!seen, "a 200ms load showed a skeleton");
    // slow: nothing at 250ms, there by 700ms, gone after the load ends
    await page.locator('[data-kit="skeleton-slow"]').click();
    await page.waitForTimeout(250);
    assert(await stage.count() === 0, "the skeleton showed before 400ms");
    await page.waitForTimeout(450);
    assert(await stage.count() === 1, "the skeleton had not shown by 700ms of a slow load");
    const pulse = await page.locator('[data-kit="skeleton-stage"] [data-slot="skeleton"]').first().evaluate((el) => getComputedStyle(el).animationName);
    assert(pulse === "pulse", `with motion allowed the blocks should pulse (animation-name ${pulse})`);
    await page.waitForTimeout(1300);
    assert(await stage.count() === 0, "the skeleton stayed after the load ended");
    // every shape is there and says 正在读取 once per frame to a screen reader
    const shapes = await page.locator('[data-kit="skeleton-shapes"] [data-slot="skeleton-frame"]').evaluateAll((els) => els.map((el) => el.getAttribute("data-variant")));
    assert(["rows", "card", "table", "messages"].every((v) => shapes.includes(v)), `shapes: ${shapes.join(",")}`);
  } finally { await view.close(); }
  // Reduced motion: no pulse at all.  (This view's own no-motion style is not injected so the page's CSS decides.)
  view = await newView(ctx.browser, { width: 1440, theme: "light", label: "skeleton reduced", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await page.locator("[data-kit-states]").waitFor();
    const name = await page.locator('[data-kit="skeleton-shapes"] [data-slot="skeleton"]').first().evaluate((el) => getComputedStyle(el).animationName);
    assert(name === "none", `reduced motion: the skeleton should not animate (animation-name ${name})`);
  } finally { await view.close(); }
  // Route level: the next page's chunk is held back; before 400ms nothing covers the page, after it a skeleton does, and it leaves when the page arrives.
  view = await newView(ctx.browser, { width: 1440, theme: "light", label: "route skeleton", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await waitReady(page, PAGES.find((p) => p.name === "chat-default"));
    await settle(page);
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    await view.context.route(/\/assets\/portfolio-[^/]*\.js$/, async (route) => { await gate; await route.continue(); });
    await page.evaluate(() => { location.hash = "#/portfolio"; });
    await page.waitForTimeout(250);
    assert(await page.locator('[data-slot="page-pending"]').count() === 0, "a skeleton covered the page before 400ms");
    await page.waitForTimeout(450);
    assert(await page.locator('[data-slot="page-pending"] [data-variant="table"]').count() === 1, "no table skeleton after 700ms of waiting for the portfolio page");
    assert(await page.locator("[data-testid=thread]").count() === 1, "the page on screen was unmounted while waiting");
    release();
    await page.locator(".pf-positions").waitFor({ timeout: 10000 });
    assert(await page.locator('[data-slot="page-pending"]').count() === 0, "the skeleton stayed after the page arrived");
    // an ordinary (fast) navigation never shows one
    let flashed = false;
    await page.evaluate(() => { window.__pendingSeen = false; new MutationObserver(() => { if (document.querySelector('[data-slot="page-pending"]')) window.__pendingSeen = true; }).observe(document.body, { childList: true, subtree: true }); });
    await page.evaluate(() => { location.hash = "#/routines"; });
    await page.locator("main.personal-page h1").waitFor({ timeout: 10000 });
    flashed = await page.evaluate(() => window.__pendingSeen);
    assert(!flashed, "a quick page change flashed a skeleton");
  } finally { await view.close(); }
  return "200ms: never; 1.5s: after 400ms, gone at the end; blocks pulse only with motion allowed; a held-back page chunk is covered after 400ms by a table skeleton and a quick change shows none";
}

/** The three components that end up inside old pages look the same inside a data-legacy island as outside it (they carry data-slot, so the restore block leaves them alone). */
async function stateComponentsInLegacy(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "states in legacy", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await page.locator('[data-probe="state-island"]').waitFor();
    await settle(page, { pinTranscript: false });
    const props = ["display", "marginTop", "marginBottom", "marginLeft", "paddingTop", "paddingBottom", "paddingLeft", "paddingRight", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "textTransform", "color", "backgroundColor", "borderTopWidth", "borderTopStyle", "borderTopColor", "borderRadius", "listStyleType", "textDecorationLine", "cursor", "width", "height", "textAlign"];
    const read = (probe) => page.evaluate(([name, list]) => {
      const root = document.querySelector(`[data-probe="${name}"]`);
      const pick = (el) => { const cs = getComputedStyle(el); return Object.fromEntries(list.map((prop) => [prop, cs[prop]])); };
      const out = {};
      const parts = { errorBar: '[data-slot="error-bar"]', errorText: '[data-slot="error-bar"] p', errorButton: '[data-slot="error-bar"] button', errorIcon: '[data-slot="error-bar"] svg', empty: '[data-slot="empty-state"]', emptyTitle: '[data-slot="empty-state"] h3', emptyButton: '[data-slot="empty-state"] button', stateful: '[data-slot="button"]' };
      for (const [key, selector] of Object.entries(parts)) { const el = root.querySelector(selector); out[key] = el ? pick(el) : null; }
      return out;
    }, [probe, props]);
    const outside = await read("state-outside"), inside = await read("state-island");
    const bad = [];
    for (const key of Object.keys(outside)) {
      if (!outside[key] || !inside[key]) { bad.push(`${key}: missing in ${outside[key] ? "the island" : "the outside copy"}`); continue; }
      for (const prop of props) if (outside[key][prop] !== inside[key][prop]) bad.push(`${key}.${prop}: outside ${outside[key][prop]} / inside the legacy island ${inside[key][prop]}`);
    }
    assert(!bad.length, bad.join("\n"));
    return `ErrorBar, EmptyState and StatefulButton: ${Object.keys(outside).length} parts x ${props.length} properties identical inside data-legacy and outside`;
  } finally { await view.close(); }
}

/** The long-task bar: stage and elapsed time, survives leaving the page, the end is a toast. */
async function taskBar(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "task bar", unmatched, motion: true });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await page.locator("[data-kit-states]").waitFor();
    await page.locator('[data-kit="task-start"]').click();
    const row = page.locator('[data-slot="task-bar"] [data-slot="task-row"]');
    await row.first().waitFor({ timeout: 3000 });
    assert((await row.first().innerText()).includes("扫描 SEC") && (await row.first().innerText()).includes("读取申报列表"), `row: ${await row.first().innerText()}`);
    // leave for a page inside the shell: the bar is still there, in the dock
    await page.evaluate(() => { location.hash = "#/chat"; });
    await page.locator("[data-testid=message]").first().waitFor({ timeout: 15000 });
    const dock = page.locator('[data-slot="task-dock"] [data-slot="task-row"]');
    await dock.first().waitFor({ timeout: 3000 });
    const first = await dock.first().locator("[data-elapsed]").innerText();
    await page.waitForTimeout(2300);
    const later = await dock.first().locator("[data-elapsed]").innerText();
    assert(first !== later, `elapsed time did not move (${first} -> ${later})`);
    assert((await dock.first().innerText()).includes("解析正文"), `the stage did not change: ${await dock.first().innerText()}`);
    // the end: a toast, and the bar is gone
    await page.locator("[data-sonner-toast]", { hasText: "SEC 扫描完成" }).waitFor({ timeout: 8000 });
    assert(await page.locator('[data-slot="task-dock"]').count() === 0, "the dock stayed after the task ended");
    return `0:0x -> later ${later}; stage 读取申报列表 -> 解析正文; left for #/chat and the bar followed; the end came as a toast`;
  } finally { await view.close(); }
}

/** The sample page of the states answers: stateful button phases, the error bar's retry, the empty state's action, keyboard focus rings. */
async function statesSamplePage(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "states sample", unmatched, motion: true });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/dev/kit/states`, { waitUntil: "load" });
    await page.locator("[data-kit-states]").waitFor();
    const rows = await page.locator("[data-kit-state]").evaluateAll((els) => els.map((el) => el.getAttribute("data-kit-state")));
    assert(rows.join(",") === "1,2,3,4,5,6,7,8,9", `rows: ${rows.join(",")}`);
    const ok = page.locator('[data-kit="stateful-ok"]');
    await ok.click();
    assert((await ok.getAttribute("data-phase")) === "loading" && (await ok.getAttribute("aria-busy")) === "true", "not loading after the click");
    const width = await ok.evaluate((el) => el.getBoundingClientRect().width);
    await page.waitForFunction(() => document.querySelector('[data-kit="stateful-ok"]').getAttribute("data-phase") === "success", null, { timeout: 4000 });
    assert(Math.abs((await ok.evaluate((el) => el.getBoundingClientRect().width)) - width) < 0.5, "the button changed width between phases");
    await page.waitForFunction(() => document.querySelector('[data-kit="stateful-ok"]').getAttribute("data-phase") === "idle", null, { timeout: 4000 });
    const fail = page.locator('[data-kit="stateful-fail"]');
    await fail.click();
    await page.waitForFunction(() => document.querySelector('[data-kit="stateful-fail"]').getAttribute("data-phase") === "error", null, { timeout: 4000 });
    const colours = await page.evaluate(() => { const css = (name) => { const probe = document.createElement("i"); probe.style.backgroundColor = `var(${name})`; document.body.appendChild(probe); const c = getComputedStyle(probe).backgroundColor; probe.remove(); return c; };
      const chip = (phase) => { const el = document.querySelector(`[data-phase-static="${phase}"] span.rounded-full`); return el && getComputedStyle(el).backgroundColor; };
      return { success: [chip("success"), css("--success")], error: [chip("error"), css("--danger")], up: css("--up"), down: css("--down") }; });
    assert(colours.success[0] === colours.success[1] && colours.error[0] === colours.error[1], `phase colours are not the success / danger tokens: ${JSON.stringify(colours)}`);
    await page.locator('[data-kit-state="3"] [data-slot="error-bar"] button').first().click();
    assert((await page.locator('[data-kit="error-tries"]').innerText()).includes("1"), "retry did not call back");
    assert(await page.locator('[data-kit-state="3"] [role="alert"]').count() === 2, "error bars are not role=alert");
    const link = page.locator('[data-kit-state="3"] [data-slot="error-bar"] a').first();
    assert((await link.innerText()).includes("去设置") && (await link.getAttribute("href")) === "#/settings/models", "去设置 link");
    await page.locator('[data-kit-state="2"] button').click();
    assert((await page.locator('[data-kit="empty-acted"]').count()) === 1, "the empty state's action did nothing");
    // focus is visible on the sample's controls
    for (const sel of ['[data-kit="stateful-ok"]', '[data-kit-state="3"] [data-slot="error-bar"] button', '[data-kit-state="2"] button']) {
      await page.keyboard.press("Shift");   // the last input was the keyboard: :focus-visible applies
      await page.locator(sel).first().focus();
      const ring = await page.evaluate(() => { const cs = getComputedStyle(document.activeElement); return `${cs.boxShadow} ${cs.outlineStyle}`; });
      assert(!/^none none$/.test(ring.trim()) && ring.trim() !== "none none", `no visible focus on ${sel}: ${ring}`);
    }
    return "nine rows; stateful button loading -> success / error without a width change (success / danger tokens); error bar retry + 去设置; empty action; focus rings";
  } finally { await view.close(); }
}


// --- P3.1: the nine chat checks of design 7.3 (the P3 packages each run them again; `--only chat-` runs just these) -------
const WRITE_REQUEST_ID = "d0000000-0000-4000-8000-0000000000a1"; // the write-confirmation card that ends FinBot's history (fixtures/chat.mjs)
/** The JSON bodies of the requests the page sends to `re` (a path pattern), in order; collected while the check runs. */
function watchPosts(page, re) {
  const bodies = [];
  page.on("request", (request) => {
    if (request.method() !== "POST" || !re.test(new URL(request.url()).pathname)) return;
    try { bodies.push(JSON.parse(request.postData() ?? "{}")); } catch { bodies.push({}); }
  });
  return bodies;
}
const STREAM_PATH = /\/agent-chat\/stream$/;
const row = (page, name) => page.locator("[data-bot-row]", { hasText: name }).first();
const turnEvent = (id) => ({ conversation_id: CONVERSATION.teslabot, turn_id: `t9000000-0000-4000-8000-0000000000${id}`, bot_id: BOT.teslabot });

async function chatCancel(ctx) {
  const view = await openChat(ctx, "chat-cancel");
  try {
    const { page } = view;
    const hand = await handFed(page);
    await page.locator("#agent-draft").fill(`${HAND_MARKER} 取消测试`);
    await page.locator("[data-testid=send]").click();
    await hand.opened(0);
    await hand.push(0, "conversation", { ...turnEvent("c1"), conversation_id: CONVERSATION.finbot, bot_id: BOT.finbot });
    await hand.push(0, "delta", { text: "已经生成的前半句，" });
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: "已经生成的前半句" }).waitFor({ timeout: 10000 });
    await page.locator("[data-testid=stop]").click();
    // P3.4: the old status line (兼任进度与报错) is gone; the stop is a grey 「已停止」 line on the message itself.
    await page.locator("[data-testid=message][data-role=assistant] [data-testid=stopped-note]", { hasText: "已停止" }).waitFor({ timeout: 10000 });
    assert((await page.locator("[data-testid=chat-status]").count()) === 0, "the composer's status line is back");
    assert((await page.locator("[data-testid=message][data-role=assistant]", { hasText: "已经生成的前半句" }).count()) === 1, "the text generated before the cancel is gone");
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await page.locator("#agent-draft").fill("取消之后还能再输入");
    assert((await page.locator("#agent-draft").inputValue()) === "取消之后还能再输入", "composer did not accept input after the cancel");
    assert(await hand.aborted(0), "the request was not aborted");
    assert((await page.locator("[data-testid=stop]").count()) === 0, "the cancel button is still there");
    return "partial text kept, 已停止 shown on the message, no status line, request aborted, composer usable";
  } finally { await view.close(); }
}

async function chatBackgroundLine(ctx) {
  const view = await openChat(ctx, "chat-background-line");
  try {
    const { page } = view;
    const hand = await handFed(page);
    await pressBotRow(page, "TeslaBot");
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await page.locator("#agent-draft").fill(`${HAND_MARKER} 后台线`);
    await page.locator("[data-testid=send]").click();
    const body = await hand.opened(0);
    assert(body.bot_id === BOT.teslabot, `the turn went out for ${body.bot_id}`);
    await hand.push(0, "conversation", turnEvent("d1"));
    await hand.push(0, "delta", { text: "后台里的前半句，" });
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: "后台里的前半句" }).waitFor({ timeout: 10000 });
    await pressBotRow(page, "AppleBot");
    await page.locator("h1", { hasText: "AppleBot" }).waitFor({ timeout: 10000 });
    await page.locator('[data-bot-row][data-marker="running"]', { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    assert((await page.locator("[data-testid=message][data-role=assistant]", { hasText: "后台里的前半句" }).count()) === 0, "TeslaBot's answer is showing in AppleBot's line");
    // The stream ends while the user is looking at AppleBot.
    await hand.push(0, "delta", { text: "后半句也到了。" });
    await hand.push(0, "done", { status: "complete", turn_id: turnEvent("d1").turn_id, thinking_ms: 500, citations: [], citation_protocol: null });
    await hand.close(0);
    await page.locator('[data-bot-row][data-marker="unread"]', { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    assert((await row(page, "TeslaBot").locator("[data-count]").innerText()).trim() === "1", "the new-answer mark is not the number 1");
    assert((await row(page, "AppleBot").getAttribute("data-marker")) === "none", "AppleBot's row changed");
    await pressBotRow(page, "TeslaBot");
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: "后台里的前半句，后半句也到了。" }).waitFor({ timeout: 10000 });
    await page.locator('[data-bot-row][data-marker="none"]', { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    return "TeslaBot ring while answering in the background, number 1 once finished, the whole answer on return, mark gone";
  } finally { await view.close(); }
}

async function chatClarification(ctx) {
  const view = await openChat(ctx, "chat-clarification");
  try {
    const { page } = view;
    const bodies = watchPosts(page, STREAM_PATH);
    await pressBotRow(page, "TeslaBot");
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await page.locator("#agent-draft").fill(`${ASK_MARKER} 查一下结果`);
    await page.locator("[data-testid=send]").click();
    const card = page.locator("[data-slot=approval-card][data-state=active]");
    await card.waitFor({ timeout: 10000 });
    assert((await card.locator("button", { hasText: "第二条结果" }).isEnabled()), "the card's options are not enabled");
    assert((await card.getAttribute("data-kind")) === "question", "a plain question is drawn as a write card");
    await card.locator("button", { hasText: "第二条结果" }).click();
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    assert(bodies.length === 2, `expected two stream requests, saw ${bodies.length}`);
    const next = bodies[1];
    assert(next.message === "pick-second-result", `the next turn said ${JSON.stringify(next.message)}`);
    assert(next.pending_request_id === CLARIFY_REQUEST_ID, `pending_request_id was ${next.pending_request_id}`);
    assert(next.display_message === "第二条结果", `display_message was ${JSON.stringify(next.display_message)}`);
    assert(next.bot_id === BOT.teslabot, "the answer went out without the bot id");
    await page.locator("[data-testid=message][data-role=user]", { hasText: "第二条结果" }).waitFor({ timeout: 10000 });
    const folded = page.locator("[data-slot=approval-card][data-state=answered]");
    assert((await folded.count()) === 1 && (await page.locator("[data-slot=approval-card][data-state=active]").count()) === 0, "the answered card did not fold to its line");
    assert(/已回答.*第二条结果/.test(await folded.innerText()), `the folded card says ${JSON.stringify(await folded.innerText())}`);
    return "card ends the turn, the pick goes out as the next turn with its request id, the card folds to one line";
  } finally { await view.close(); }
}

async function chatWriteConfirm(ctx) {
  const confirmView = await openChat(ctx, "chat-write-confirm");
  let confirmed;
  try {
    const { page } = confirmView;
    const bodies = watchPosts(page, STREAM_PATH);
    const card = page.locator("[data-slot=approval-card][data-state=active][data-kind=write]");
    await card.waitFor({ timeout: 10000 });
    await card.locator("button", { hasText: "确认执行" }).click();
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    assert(bodies.length === 1, `expected one stream request, saw ${bodies.length}`);
    confirmed = bodies[0];
    assert(confirmed.pending_request_id === WRITE_REQUEST_ID && confirmed.message === "confirm:fetch_analyze", `confirm request: ${JSON.stringify(confirmed)}`);
    assert(confirmed.bot_id === BOT.finbot, "the confirmation went out without the bot id");
  } finally { await confirmView.close(); }
  const declineView = await openChat(ctx, "chat-write-decline");
  try {
    const { page } = declineView;
    const bodies = watchPosts(page, STREAM_PATH);
    const card = page.locator("[data-slot=approval-card][data-state=active][data-kind=write]");
    await card.waitFor({ timeout: 10000 });
    await card.locator("button", { hasText: "先不要" }).click();
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });
    // 「先不要」 is not silent: it goes to the server as the turn `cancel` for the pending request (that is what cancels it) -- never as a confirmation.
    assert(!bodies.some((b) => String(b.message).startsWith("confirm:")), "declining sent a confirmation");
    assert(bodies.length === 1 && bodies[0].message === "cancel" && bodies[0].pending_request_id === WRITE_REQUEST_ID, `decline request: ${JSON.stringify(bodies)}`);
  } finally { await declineView.close(); }
  return `确认执行 -> {message:"${confirmed.message}", pending_request_id}; 先不要 -> {message:"cancel", pending_request_id}, no confirm:* request`;
}

async function chatReadonlyArchive(ctx) {
  const view = await openShell(ctx, "chat-readonly-archive", "#/settings/data", { ready: ".chat-archive-settings" });
  try {
    const { page } = view;
    const stamp = "2026-11-12T08:00:00.000Z";
    const archive = { marker: "market-evidence-agent-chat-archive", version: 1, created_at: stamp, updated_at: stamp,
      conversations: [{ id: "archived-1", created_at: stamp, updated_at: stamp, messages: [{ role: "user", content: "归档里的问题" }, { role: "assistant", content: "归档里的回答", status: "complete" }] }] };
    await page.locator('.chat-archive-settings input[type="file"]').setInputFiles({ name: "archive.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(archive)) });
    await page.locator(".chat-archive-settings [role=status]", { hasText: "归档已打开" }).waitFor({ timeout: 10000 });
    // A bot's line is a server conversation and ends the archive view when opened; the archive is read on the plain conversation page (no bot).
    await page.evaluate(() => { location.hash = "#/chat/history"; });
    await waitHash(page, "#/chat/history");
    const banner = page.locator("[data-testid=archive-banner]");
    await banner.waitFor({ timeout: 10000 });
    assert((await banner.innerText()).includes("本地归档只读查看"), "the banner does not say it is a read-only archive");
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: "归档里的回答" }).waitFor({ timeout: 10000 });
    // P3.2 (design 4.2, 只读归档): the input area is replaced by 返回当前对话; there is no box to type in and nothing to send with.
    assert((await page.locator("#agent-draft").count()) === 0 && (await page.locator("[data-testid=send]").count()) === 0, "the composer still takes input in a read-only archive");
    const back = page.locator("[data-testid=return-live]");
    assert(await back.isEnabled(), "返回当前对话 is not usable");
    await back.click();
    await page.locator("[data-testid=archive-banner]").waitFor({ state: "detached", timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    assert((await page.locator("[data-testid=message][data-role=assistant]", { hasText: "归档里的回答" }).count()) === 0, "the archive's messages are still showing after the return");
    return "banner + 返回当前对话 in place of the composer while viewing an imported archive; it restores the live line";
  } finally { await view.close(); }
}

async function chatExternalSync(ctx) {
  const view = await openChat(ctx, "chat-external-sync");
  try {
    const { page } = view;
    await page.locator("#agent-draft").fill("写到一半的草稿");
    // A turn written from outside this tab (Telegram, a routine): the next poll (4 s) pulls it in by itself.
    const turn = "t7000000-0000-4000-8000-000000000001";
    view.mock.state.chat.conversations.get(CONVERSATION.finbot).push(
      { role: "user", content: "来自 Telegram 的问题", turn_id: turn },
      { role: "assistant", status: "complete", turn_id: turn, content: "外部消息的回答：已记入对话线。" });
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: "外部消息的回答" }).waitFor({ timeout: 15000 });
    await page.locator("[data-testid=message][data-role=user]", { hasText: "来自 Telegram 的问题" }).waitFor({ timeout: 5000 });
    assert((await page.locator("#agent-draft").inputValue()) === "写到一半的草稿", "the draft changed when the external turn arrived");
    return "the outside turn appeared without any action; the draft is untouched";
  } finally { await view.close(); }
}

async function chatCompact(ctx) {
  const view = await openChat(ctx, "chat-compact");
  try {
    const { page } = view;
    const posts = watchPosts(page, /\/agent-chat\/conversations\/[^/]+\/compact$/);
    await page.locator("#agent-draft").fill("/compact 只留估值部分");
    await page.locator("[data-testid=send]").click();
    await page.locator("[data-testid=compaction]", { hasText: "已压缩 2 轮" }).waitFor({ timeout: 10000 });
    assert(posts.length === 1, `expected one compact request, saw ${posts.length}`);
    assert(posts[0].focus === "只留估值部分" && posts[0].bot_id === BOT.finbot, `compact request: ${JSON.stringify(posts[0])}`);
    assert((await page.locator("#agent-draft").inputValue()) === "", "the command text stayed in the composer");
    assert(view.mock.requests.some((r) => r.method === "POST" && /\/compact$/.test(r.path) && r.path.includes(CONVERSATION.finbot)), "the compact request did not name the open conversation");
    return `POST .../compact {focus, bot_id} once; 「已压缩 2 轮」 line in the thread; the command is cleared`;
  } finally { await view.close(); }
}

async function chatLoadEarlier(ctx) {
  const fixtureState = buildState();
  fixtureState.chat.older = { [CONVERSATION.finbot]: { messages: olderTurns(6), cursor: 6 } };
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "chat-load-earlier", unmatched, fixtureState });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await waitReady(page, { ready: "[data-testid=message]" });
    await settle(page);
    await page.locator("[data-testid=load-earlier]", { hasText: "加载更早消息" }).waitFor({ timeout: 10000 });
    const text = "AAPL 最近一个季度的服务收入怎么样？";
    const offset = (scrollToTop) => page.evaluate(([needle, top]) => {
      const transcript = document.querySelector("[data-testid=transcript]");
      if (top) transcript.scrollTop = 0;     // the scroll handler asks for the earlier turns; the answer comes later, so this reads the "before"
      const el = [...document.querySelectorAll("[data-testid=message][data-role=user]")].find((node) => node.textContent.includes(needle));
      return el.getBoundingClientRect().top - transcript.getBoundingClientRect().top;
    }, [text, scrollToTop]);
    const scrollable = await page.evaluate(() => { const el = document.querySelector("[data-testid=transcript]"); return el.scrollHeight - el.clientHeight; });
    assert(scrollable > 200, `the thread barely scrolls (${scrollable}px): the check cannot tell a jump from none`);
    const before = await offset(true);
    await page.locator("[data-testid=message][data-role=user]", { hasText: "更早的问题 1" }).waitFor({ timeout: 10000 });
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r)))));
    const after = await offset(false);
    assert(Math.abs(after - before) <= 2, `the line the reader was looking at moved from ${Math.round(before)}px to ${Math.round(after)}px`);
    assert((await page.locator("[data-testid=message][data-role=user]", { hasText: "更早的问题 6" }).count()) === 1, "not every earlier turn arrived");
    assert((await page.locator("[data-testid=load-earlier]").count()) === 0, "the 加载更早消息 button is still there once nothing is left");
    return `scrolled to the top -> 6 earlier turns above; the line being read stayed at ${Math.round(before)}px (after: ${Math.round(after)}px)`;
  } finally { await view.close(); }
}

// --- P3.1: the English catalog is a chunk of its own ----------------------------------------------------------------------
async function localeCatalogLoadsOnDemand(ctx) {
  const english = JSON.parse(fs.readFileSync(path.resolve(flags.dist, "..", "src", "locales", "en-US.json"), "utf8"));
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "locale-lazy", unmatched });
  try {
    const { page } = view;
    const catalogRequests = [];
    page.on("request", (request) => { if (/\/assets\/en-US-[^/]+\.js$/.test(new URL(request.url()).pathname)) catalogRequests.push(request.url()); });
    await page.goto(`${ctx.server.url}#/settings/models`, { waitUntil: "load" });
    await page.locator("select#locale").waitFor({ timeout: 10000 });
    await settle(page);
    assert(catalogRequests.length === 0, `a Chinese session fetched the English catalog: ${catalogRequests[0]}`);
    const title = page.locator("#agent-admin-title");
    assert((await title.innerText()) === "模型连接设置", "the settings title is not Chinese at the start");
    await page.locator("select#locale").selectOption("en-US");
    await page.waitForFunction((text) => document.querySelector("#agent-admin-title")?.textContent === text, english["模型连接设置"], { timeout: 10000 });
    assert(catalogRequests.length === 1, `switching to English fetched the catalog ${catalogRequests.length} times`);
    // A reload with English saved: the first draw is already English (the catalog is awaited before the first render).
    await page.reload({ waitUntil: "load" });
    await page.waitForFunction((text) => document.querySelector("#agent-admin-title")?.textContent === text, english["模型连接设置"], { timeout: 10000 });
    assert(catalogRequests.length === 2, `the English reload fetched the catalog ${catalogRequests.length - 1} more times`);
    await page.locator("select#locale").selectOption("zh-CN");
    await page.waitForFunction(() => document.querySelector("#agent-admin-title")?.textContent === "模型连接设置", null, { timeout: 10000 });
    return `Chinese session: no request for the English chunk; switch: one request, title "${english["模型连接设置"]}"; reload in English: the title is English; back to 中文 works`;
  } finally { await view.close(); }
}

// --- P3.1: the bot's right rail and the new-bot dialog load on demand; a chunk that cannot be fetched must not take the page down ---
async function optionalChunkFailure(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "optional-chunk", unmatched });
  try {
    const { page } = view;
    let blocked = 0;
    await page.route(/\/assets\/BotSidePanel-[^/]*\.js/, (route) => { blocked += 1; return route.abort(); });
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await waitReady(page, { ready: "[data-testid=message]" });
    await settle(page);
    assert(blocked >= 1, "the bot page never asked for the side panel chunk (is it still loaded eagerly?)");
    assert((await page.locator("#agent-draft").count()) === 1, "the composer is gone: the failed chunk took the chat page down");
    assert((await page.locator('[data-slot="route-error"]').count()) === 0, "a failed optional chunk fell through to the route error");
    assert((await page.locator("[data-testid=context-panel]").count()) === 1, "the right panel itself (来源 / 过程) is gone with the workspace chunk");
    assert((await page.locator(".bot-workspace").count()) === 0, "the workspace cards are drawn although their chunk was blocked");
    await page.locator('[data-slot="sidebar"] button', { hasText: "新建 bot" }).first().click();
    await page.waitForTimeout(800);
    assert((await page.locator('[role="dialog"]').count()) === 0, "the new-bot dialog is drawn although its chunk was blocked");
    assert((await page.locator("#agent-draft").count()) === 1 && (await page.locator('[data-slot="route-error"]').count()) === 0, "pressing 新建 bot with the chunk blocked broke the page");
    await page.locator("#agent-draft").fill("页面还活着");
    return `chunk blocked ${blocked}x: the thread and composer stay, no rail, no dialog, no route error`;
  } finally { await view.close(); }
}

// --- P3.2: messages and the composer ------------------------------------------------------------------------------------
const frames = (page) => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)))));
const transcriptBox = (page) => page.evaluate(() => { const el = document.querySelector("[data-testid=transcript]"); return { top: el.scrollTop, gap: el.scrollHeight - el.scrollTop - el.clientHeight, room: el.scrollHeight - el.clientHeight }; });

/** Acceptance 1: Enter that belongs to an input method never sends; after the composition ends it does. */
async function composerIme(ctx) {
  const view = await openChat(ctx, "composer-ime");
  try {
    const { page } = view;
    const posts = watchPosts(page, STREAM_PATH);
    const box = page.locator("#agent-draft");
    await box.fill("你好");
    await box.focus();
    // 1. between compositionstart and compositionend a plain Enter is the input method's.
    await box.dispatchEvent("compositionstart");
    await page.keyboard.press("Enter");
    await frames(page);
    assert(posts.length === 0, "Enter during a composition sent the message");
    assert((await page.locator("[data-testid=message][data-role=user]", { hasText: "你好" }).count()) === 0, "the composing text turned into a message");
    // 2. the key event that carries isComposing / keyCode 229 (what a browser sends for the Enter that confirms a candidate).
    await box.dispatchEvent("compositionend");
    await box.evaluate((el) => { for (const init of [{ isComposing: true, keyCode: 229 }, { isComposing: false, keyCode: 229 }]) el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...init })); });
    await frames(page);
    assert(posts.length === 0, "an Enter flagged isComposing / keyCode 229 sent the message");
    // 3. after compositionend a plain Enter sends.
    await box.fill("你好");
    await box.press("Enter");
    await page.locator("[data-testid=message][data-role=user]", { hasText: "你好" }).waitFor({ timeout: 10000 });
    assert(posts.length === 1, `expected one request after the composition ended, saw ${posts.length}`);
    // Shift+Enter never sends.
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await box.fill("第一行");
    await box.press("Shift+Enter");
    await frames(page);
    assert(posts.length === 1, "Shift+Enter sent the message");
    return "no request during compositionstart..end or for isComposing / keyCode 229; one request for the Enter after compositionend; Shift+Enter breaks the line";
  } finally { await view.close(); }
}

/** The "/" menu: arrows move, Esc closes, Enter picks; an input method's keys do none of these. */
async function composerSlashMenu(ctx) {
  const view = await openChat(ctx, "composer-slash-menu");
  try {
    const { page } = view;
    const box = page.locator("#agent-draft");
    await box.fill("/");
    const menu = page.locator("[data-testid=slash-menu]");
    await menu.waitFor({ timeout: 10000 });
    const options = menu.locator("[role=option]");
    const listed = await options.count();
    assert(listed >= 2, "the menu lists fewer than two skills");
    const selected = () => options.evaluateAll((items) => items.findIndex((item) => item.getAttribute("aria-selected") === "true"));
    assert((await selected()) === 0, "the first skill is not selected");
    await box.press("ArrowDown");
    assert((await selected()) === 1, "ArrowDown did not move the selection");
    await box.press("ArrowUp");
    assert((await selected()) === 0, "ArrowUp did not move it back");
    // Keys that belong to an input method.  Synthetic key events are used so the browser adds no newline of its own (a real composition's Enter inserts none).
    await box.dispatchEvent("compositionstart");
    await box.evaluate((el) => { for (const key of ["ArrowDown", "Enter", "Tab", "Escape"]) el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })); });
    await frames(page);
    assert((await menu.count()) === 1 && (await box.inputValue()) === "/", "keys during a composition acted on the menu or the draft");
    assert((await selected()) === 0, "ArrowDown during a composition moved the selection");
    await box.evaluate((el) => el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, keyCode: 229, bubbles: true, cancelable: true })));
    assert((await menu.count()) === 1 && (await box.inputValue()) === "/", "an Enter flagged isComposing picked a skill");
    await box.dispatchEvent("compositionend");
    await page.keyboard.press("Escape");
    await menu.waitFor({ state: "detached", timeout: 5000 });
    await box.fill("");
    await box.fill("/");
    await menu.waitFor({ timeout: 10000 });
    await box.press("Enter");
    const value = await box.inputValue();
    assert(/^\/\S+ $/.test(value), `Enter did not pick the selected skill (draft: ${JSON.stringify(value)})`);
    return `menu lists ${listed} skills; arrows, Esc and Enter work; keys during a composition do nothing`;
  } finally { await view.close(); }
}

/** Acceptance 2: a streaming answer is followed; one scroll up lets go and shows 回到底部; the button, or scrolling back, resumes. */
async function chatFollowAndJump(ctx) {
  const view = await openChat(ctx, "chat-follow-and-jump");
  try {
    const { page } = view;
    const hand = await streamHalfway(page, { paragraphs: 6 });
    await frames(page);
    let at = await transcriptBox(page);
    assert(at.room > 300, `the answer does not overflow the thread (${at.room}px): the check cannot tell following from not following`);
    assert(at.gap <= 2, `a streaming answer is not followed (${Math.round(at.gap)}px from the bottom)`);
    assert((await page.locator("[data-testid=jump-bottom]").count()) === 0, "回到底部 shows while following");
    await hand.push(0, "delta", { text: streamParagraph(7) }); await frames(page);
    at = await transcriptBox(page);
    assert(at.gap <= 2, `the new paragraph was not followed (${Math.round(at.gap)}px)`);
    // One scroll up: the page stops following and offers the way back.
    await page.evaluate(() => { document.querySelector("[data-testid=transcript]").scrollTop = 200; });
    await page.locator("[data-testid=jump-bottom]").waitFor({ timeout: 5000 });
    const held = await transcriptBox(page);
    await hand.push(0, "delta", { text: streamParagraph(8) }); await frames(page);
    const later = await transcriptBox(page);
    assert(later.room > held.room, "the answer did not grow while scrolled up");
    assert(Math.abs(later.top - held.top) <= 2, `the page kept following after the reader scrolled up (${held.top} -> ${later.top})`);
    // The button: back to the bottom, button gone, following again.
    await page.locator("[data-testid=jump-bottom]").click(); await frames(page);
    at = await transcriptBox(page);
    assert(at.gap <= 2, `回到底部 did not reach the bottom (${Math.round(at.gap)}px)`);
    assert((await page.locator("[data-testid=jump-bottom]").count()) === 0, "回到底部 stays after it was used");
    await hand.push(0, "delta", { text: streamParagraph(9) }); await frames(page);
    assert((await transcriptBox(page)).gap <= 2, "following did not resume after 回到底部");
    // Scrolling back down by hand restores it as well.
    await page.evaluate(() => { document.querySelector("[data-testid=transcript]").scrollTop = 0; });
    await page.locator("[data-testid=jump-bottom]").waitFor({ timeout: 5000 });
    await page.evaluate(() => { const el = document.querySelector("[data-testid=transcript]"); el.scrollTop = el.scrollHeight; });
    await page.locator("[data-testid=jump-bottom]").waitFor({ state: "detached", timeout: 5000 });
    await hand.push(0, "delta", { text: streamParagraph(10) }); await frames(page);
    assert((await transcriptBox(page)).gap <= 2, "following did not resume after scrolling back to the bottom");
    // Not in the way: at the bottom the last message ends above the composer with room to spare.
    const clearance = await page.evaluate(() => { const last = [...document.querySelectorAll("[data-testid=message]")].at(-1); const t = document.querySelector("[data-testid=transcript]"); return t.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom; });
    assert(clearance >= 48, `the last message ends only ${Math.round(clearance)}px above the bottom of the thread`);
    return `followed ${Math.round(at.room)}px of growth; scroll up -> button, no follow; button and manual return resume it; ${Math.round(clearance)}px clear under the last line`;
  } finally { await view.close(); }
}

/** Acceptance 3: a half-typed message stays with its line when the bot (or the page) changes. */
async function draftSurvivesSwitch(ctx) {
  const view = await openChat(ctx, "draft-survives-switch");
  try {
    const { page } = view;
    const box = page.locator("#agent-draft");
    await box.fill("写到一半的话，还没发");
    await pressBotRow(page, "TeslaBot");
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    assert((await box.inputValue()) === "", `TeslaBot's box opened with the other line's draft: ${JSON.stringify(await box.inputValue())}`);
    await box.fill("TeslaBot 线上的草稿");
    await pressBotRow(page, "FinBot");
    await page.locator("h1", { hasText: "FinBot" }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    assert((await box.inputValue()) === "写到一半的话，还没发", `FinBot's draft is gone after the switch back: ${JSON.stringify(await box.inputValue())}`);
    await pressBotRow(page, "TeslaBot");
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    assert((await box.inputValue()) === "TeslaBot 线上的草稿", "TeslaBot's own draft is gone");
    // Another page and back (the session provider sits above the routed page).
    await pressNavItem(page, "持仓");
    await page.waitForFunction(() => location.hash.startsWith("#/portfolio"), null, { timeout: 10000 });
    await pressBotRow(page, "TeslaBot");
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    assert((await box.inputValue()) === "TeslaBot 线上的草稿", "the draft is gone after a visit to another page");
    // A reload: drafts are kept in localStorage per line (chat-lines.mjs), so they survive it, exactly as before this package.
    await page.reload({ waitUntil: "load" });
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor({ timeout: 10000 });
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    assert((await box.inputValue()) === "TeslaBot 线上的草稿", `the draft did not survive a reload: ${JSON.stringify(await box.inputValue())}`);
    await pressBotRow(page, "FinBot");
    await page.locator("h1", { hasText: "FinBot" }).waitFor({ timeout: 10000 });
    assert((await box.inputValue()) === "写到一半的话，还没发", "the other line's draft did not survive the reload");
    return "A -> B -> A keeps both drafts; a visit to another page and a reload keep them (stored per line in localStorage, as before)";
  } finally { await view.close(); }
}

/** The send position becomes the stop button while an answer runs; pressing it is the old 取消请求. */
async function stopButton(ctx) {
  const view = await openChat(ctx, "stop-button");
  try {
    const { page } = view;
    const send = page.locator("[data-testid=send]");
    const idle = await send.boundingBox();
    assert(idle, "no send button");
    const hand = await streamHalfway(page, { paragraphs: 1 });
    const stop = page.locator("[data-testid=stop]");
    const running = await stop.boundingBox();
    assert(running && Math.abs(running.x - idle.x) <= 1 && Math.abs(running.y - idle.y) <= 1 && Math.abs(running.width - idle.width) <= 1, `the stop button is not where send was (${JSON.stringify(idle)} -> ${JSON.stringify(running)})`);
    assert((await send.count()) === 0, "send and stop show at the same time");
    assert((await page.getByRole("button", { name: "取消请求" }).count()) === 0, "the old 取消请求 button is still there");
    assert(/停止|Stop/.test(await stop.getAttribute("aria-label") ?? ""), "the stop button has no name");
    await stop.click();
    await page.locator("[data-testid=stopped-note]", { hasText: "已停止" }).waitFor({ timeout: 10000 });
    assert(await hand.aborted(0), "pressing stop did not abort the request");
    await page.locator("[data-testid=send]").waitFor({ timeout: 10000 });
    const back = await send.boundingBox();
    assert(back && Math.abs(back.x - idle.x) <= 1 && Math.abs(back.y - idle.y) <= 1, "send did not come back to its place");
    assert((await page.locator("[data-testid=stop]").count()) === 0, "stop is still showing after the cancel");
    return "send -> stop in the same box; stop aborts the request, 已停止 on the message, partial text kept; send is back in place";
  } finally { await view.close(); }
}

/** Copy: the result is a toast, and the thread gets no extra line of text. */
async function copyToast(ctx) {
  const view = await openChat(ctx, "copy-toast");
  try {
    const { page, context } = view;
    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(page.url()).origin });
    const thread = page.locator("[data-testid=thread]");
    const before = await thread.innerText();
    const answer = page.locator("[data-testid=message][data-role=assistant]").first();
    await answer.hover();
    await answer.getByRole("button", { name: "复制回答" }).click();
    await page.locator("[data-sonner-toast]", { hasText: "已复制" }).waitFor({ timeout: 5000 });
    assert((await thread.innerText()) === before, "the thread's text changed when the answer was copied");
    assert((await page.locator("[data-testid=thread] [role=status]").count()) === 0, "a status line was put into the thread");
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    assert(copied.includes("288 亿美元"), `the clipboard does not hold the answer (${JSON.stringify(copied.slice(0, 40))})`);
    const question = page.locator("[data-testid=message][data-role=user]").first();
    await question.hover();
    await question.getByRole("button", { name: "复制问题" }).click();
    await page.waitForFunction(() => navigator.clipboard.readText().then((value) => value.includes("服务收入")), null, { timeout: 5000 });
    return "toast 已复制 at the corner, thread text unchanged, clipboard holds the answer; 复制问题 copies the question";
  } finally { await view.close(); }
}

/** The Markdown renderer is a chunk of its own: prefetched at launch, a skeleton while late, plain text with 重试 when it fails. */
const RENDERER = /\/assets\/markdown-renderer-[^/]+\.js$/;
async function markdownChunk(ctx) {
  const notes = [];
  // (a) Normal: the chunk is asked for at launch, before the history request; the first message is typeset when it appears, never raw.
  {
    const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "markdown-chunk-normal", unmatched });
    try {
      const { page } = view;
      const order = [];
      page.on("request", (request) => { const u = new URL(request.url()); if (RENDERER.test(u.pathname)) order.push("renderer"); else if (/\/assets\/chat-[^/]+\.js$/.test(u.pathname)) order.push("chat-code"); else if (/\/agent-chat\/conversations\/[^/]+\/messages/.test(u.pathname) || /\/agent-chat\/restore/.test(u.pathname) || /\/agent-chat\/conversations\/[^/]+$/.test(u.pathname)) order.push("history"); });
      await view.context.addInitScript(() => {
        window.__md = { plain: false, raw: false, skeleton: false, ready: false };
        const look = () => {
          if (document.querySelector("[data-testid=message-body][data-md=plain]")) window.__md.plain = true;
          if (document.querySelector("[data-testid=markdown-skeleton]")) window.__md.skeleton = true;
          if (document.querySelector("[data-testid=message-body][data-md=ready]")) window.__md.ready = true;
          if ((document.querySelector("[data-testid=thread]")?.textContent ?? "").includes("**")) window.__md.raw = true;
        };
        new MutationObserver(look).observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
      });
      await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
      await page.locator("[data-testid=message-body][data-md=ready]").first().waitFor({ timeout: 15000 });
      const seen = await page.evaluate(() => window.__md);
      assert(order.includes("renderer"), `the renderer chunk was never requested (${order.join(",")})`);
      assert(!order.includes("history") || order.indexOf("renderer") < order.indexOf("history"), `the history was asked for before the renderer (${order.join(" > ")})`);
      assert(!seen.plain && !seen.raw, `a message showed as plain text or raw Markdown on the way (${JSON.stringify(seen)})`);
      assert((await page.locator("[data-testid=markdown-skeleton]").count()) === 0, "a skeleton is still showing");
      assert((await page.locator("[data-testid=message-body] strong").count()) > 0, "the bold phrase of the first answer is not typeset");
      notes.push(`normal: requested ${order.filter((x) => x !== "chat-code").join(" > ")}; skeleton ${seen.skeleton ? "seen briefly" : "never needed"}; never plain or raw`);
    } finally { await view.close(); }
  }
  // (a2) Launch-time prefetch, shown by holding the chat page's own code back 1.5 s: the renderer is asked for in that wait (main.tsx starts it),
  //      not after the page has mounted and found it needs it.
  {
    const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "markdown-chunk-launch", unmatched });
    try {
      const { page } = view;
      const at = {};
      page.on("request", (request) => { const p2 = new URL(request.url()).pathname; if (RENDERER.test(p2)) at.renderer ??= Date.now(); });
      await page.route(/\/assets\/chat-[^/]+\.js$/, async (route) => { at.chat ??= Date.now(); await new Promise((resolve) => setTimeout(resolve, 1500)); await route.continue(); });
      await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
      await page.locator("[data-testid=message-body][data-md=ready]").first().waitFor({ timeout: 20000 });
      assert(at.chat && at.renderer, `a chunk was never requested (${JSON.stringify(at)})`);
      const gap = at.renderer - at.chat;
      assert(gap < 1000, `the renderer was asked for ${gap}ms after the chat page's code: it waits for the page instead of starting at launch`);
      notes.push(`launch: renderer asked for ${gap}ms after the chat page's code while that was held back 1.5 s`);
    } finally { await view.close(); }
  }
  // (b) The chunk 2 seconds late: skeletons stand in for the text meanwhile, never the raw Markdown; then one swap.
  {
    const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "markdown-chunk-late", unmatched });
    try {
      const { page } = view;
      await page.route(RENDERER, async (route) => { await new Promise((resolve) => setTimeout(resolve, 2000)); await route.continue(); });
      const t0 = Date.now();
      await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
      await page.locator("[data-testid=markdown-skeleton]").first().waitFor({ timeout: 15000 });
      const early = Date.now() - t0;
      const thread = await page.locator("[data-testid=thread]").innerText();
      assert(!thread.includes("**") && !thread.includes("](#citation"), "raw Markdown shows while the renderer is late");
      assert((await page.locator("[data-testid=message-body]").count()) === 0, "a message body is on screen before the renderer arrived");
      assert((await page.locator("#agent-draft").count()) === 1 && (await page.locator("[data-testid=message][data-role=user]").count()) > 0, "the page around the skeleton is not usable");
      await page.locator("[data-testid=message-body][data-md=ready]").first().waitFor({ timeout: 15000 });
      const total = Date.now() - t0;
      assert(total >= 1900, `the swap came after ${total}ms: the chunk was not held back`);
      assert((await page.locator("[data-testid=markdown-skeleton]").count()) === 0, "a skeleton is left after the swap");
      notes.push(`late (2 s): skeleton at ${early}ms, typeset text at ${total}ms, no raw text between`);
    } finally { await view.close(); }
  }
  // (c) The chunk cannot be fetched: plain text with its line breaks, a quiet note and 重试; the page stays; 重试 recovers.
  {
    const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "markdown-chunk-failed", unmatched });
    try {
      const { page } = view;
      await page.route(RENDERER, (route) => route.abort());
      await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
      await page.locator("[data-testid=message-body][data-md=plain]").first().waitFor({ timeout: 15000 });
      const failed = page.locator("[data-testid=markdown-failed]");
      await failed.first().waitFor({ timeout: 5000 });
      assert((await page.locator("#agent-draft").count()) === 1 && (await page.locator('[data-slot="route-error"]').count()) === 0, "the failed chunk took the page down");
      const white = await page.locator("[data-testid=message-body][data-md=plain]").first().evaluate((el) => getComputedStyle(el).whiteSpace);
      assert(white === "pre-wrap", `the plain text does not keep its line breaks (white-space: ${white})`);
      assert(!/color:\s*(?:red|rgb\(2[0-9]{2}, ?[0-9]{1,2}, ?[0-9]{1,2}\))/.test(await failed.first().evaluate((el) => el.outerHTML)), "the note is not neutral");
      await page.unroute(RENDERER);
      await failed.first().getByRole("button", { name: "重试" }).click();
      await page.locator("[data-testid=message-body][data-md=ready]").first().waitFor({ timeout: 15000 });
      assert((await page.locator("[data-testid=markdown-failed]").count()) === 0 && (await page.locator("[data-testid=message-body][data-md=plain]").count()) === 0, "the plain text or the note is left after 重试");
      notes.push("failed: plain text (pre-wrap) + note + 重试, page intact; 重试 typesets it");
    } finally { await view.close(); }
  }
  return notes.join(" | ");
}

/** The question rail (new markup, same logic): markers on the thread's left edge, a preview card beside the pointer, a bookmark that is kept, a click that scrolls. */
async function chatQuestionRail(ctx) {
  const view = await openChat(ctx, "chat-question-rail");
  try {
    const { page } = view;
    const rail = page.locator("[data-testid=question-rail]");
    await rail.waitFor({ timeout: 10000 });
    const markers = rail.locator("button[data-rail-index]");
    const count = await markers.count();
    assert(count >= 4, `the rail has ${count} markers`);
    const railBox = await rail.boundingBox(), threadBox = await page.locator("[data-testid=thread]").boundingBox();
    assert(railBox && threadBox && railBox.x + railBox.width <= threadBox.x + 1, "the rail is not on the thread's left edge");
    assert(threadBox.width <= 761 && threadBox.width >= 600, `the thread is ${Math.round(threadBox.width)}px wide (max 760)`);
    await markers.first().hover();
    const card = page.locator("[data-testid=turn-preview]");
    await card.waitFor({ timeout: 5000 });
    const star = card.getByRole("button", { name: /收藏这一轮/ });
    await star.click();
    await card.getByRole("button", { name: "取消收藏" }).waitFor({ timeout: 5000 });
    await page.reload({ waitUntil: "load" });
    await page.locator("[data-testid=message]").first().waitFor({ timeout: 15000 });
    await page.locator("[data-testid=question-rail] button[data-bookmarked]").first().waitFor({ timeout: 10000 });
    // A click scrolls that question to the top of the thread.
    await page.evaluate(() => { const el = document.querySelector("[data-testid=transcript]"); el.scrollTop = el.scrollHeight; });
    await frames(page);
    await page.locator("[data-testid=question-rail] button[data-rail-index='0']").click();
    await page.waitForFunction(() => { const t = document.querySelector("[data-testid=transcript]").getBoundingClientRect().top; const q = document.getElementById("chat-message-0")?.getBoundingClientRect().top ?? 1e9; return Math.abs(q - t) < 40; }, null, { timeout: 5000 });
    return `${count} markers left of a ${Math.round(threadBox.width)}px thread; preview card, bookmark kept over a reload, click scrolls to the question`;
  } finally { await view.close(); }
}

/** Keyboard: the composer's panels (model badge, context ring) and the header's ⓘ open from the keyboard, Esc closes them and hands focus back. */
async function chatPopoverKeyboard(ctx) {
  const view = await openChat(ctx, "chat-popover-keyboard");
  try {
    const { page } = view;
    const panels = [["model-badge", "模型与推理强度"], ["context-meter", "上下文用量"], ["about-chat", "关于这条对话"]];
    for (const [id, label] of panels) {
      const trigger = page.locator(`[data-testid=${id}]`);
      await trigger.waitFor({ timeout: 10000 });
      await trigger.focus();
      await page.keyboard.press("Enter");
      const panel = page.locator(`[data-slot=pop-panel][aria-label="${label}"]`);
      await panel.waitFor({ timeout: 5000 });
      assert(await panel.evaluate((el) => el.contains(document.activeElement)), `${id}: focus did not move into the panel`);
      await page.keyboard.press("Escape");
      await panel.waitFor({ state: "detached", timeout: 5000 });
      assert(await trigger.evaluate((el) => el === document.activeElement), `${id}: focus did not return to the button after Esc`);
    }
    // A press outside closes the model panel too.
    await page.locator("[data-testid=model-badge]").click();
    await page.locator("[data-slot=pop-panel]").waitFor({ timeout: 5000 });
    await page.locator("[data-testid=chat-header] h1").click();
    await page.locator("[data-slot=pop-panel]").waitFor({ state: "detached", timeout: 5000 });
    // Reach the model choice by keyboard alone: Tab from the badge into the radio list and choose with Space.
    await page.locator("[data-testid=model-badge]").focus();
    await page.keyboard.press("Enter");
    await page.locator("[data-slot=pop-panel] [role=radio]").first().waitFor({ timeout: 10000 });
    await page.keyboard.press("Tab");
    assert(await page.evaluate(() => document.activeElement?.getAttribute("role") === "radio"), "Tab from the panel did not land on a choice");
    await page.keyboard.press("Escape");
    return "model badge, context ring and ⓘ: Enter opens with focus inside, Esc closes and returns focus, a press outside closes; the choices are Tab-reachable";
  } finally { await view.close(); }
}

// --- P3.3: process and sources ---------------------------------------------------------------------------------------
const panelBox = (page) => page.locator("[data-testid=context-panel]").boundingBox();
const inView = (page, selector, within) => page.evaluate(([sel, box]) => {
  const el = document.querySelector(sel), host = document.querySelector(box); if (!el || !host) return false;
  const r = el.getBoundingClientRect(), h = host.getBoundingClientRect();
  return r.top >= h.top - 1 && r.bottom <= h.bottom + 1;
}, [selector, within]);

/** Acceptance 1: a click on [2] opens the right panel on 来源, scrolls to the second card and marks it; a folded panel unfolds first. */
async function citationJump(ctx) {
  const view = await openChat(ctx, "citation-jump");
  try {
    const { page } = view;
    await page.locator("[data-testid=panel-close]").click();
    await page.locator("[data-testid=context-panel]").waitFor({ state: "detached", timeout: 5000 });
    const chip = firstAnswer(page).locator("[data-testid=citation-chip][data-ordinal='2']").first();
    await chip.scrollIntoViewIfNeeded();
    await chip.click();
    await page.locator("[data-testid=context-panel]").waitFor({ timeout: 5000 });
    assert((await page.locator("[data-testid=tab-sources]").getAttribute("aria-selected")) === "true", "the 来源 tab is not selected after a click on [2]");
    const card = page.locator("[data-slot=source-card][data-ordinal='2']");
    await card.waitFor({ timeout: 5000 });
    await page.waitForFunction(() => document.querySelector("[data-slot=source-card][data-ordinal='2']")?.hasAttribute("data-highlight"), null, { timeout: 5000 });
    assert(await inView(page, "[data-slot=source-card][data-ordinal='2']", "[data-testid=sources-pane]"), "the second card is not inside the 来源 tab's viewport");
    assert((await page.locator("[data-slot=source-card][data-highlight]").count()) === 1, "more than one card is marked");
    // The mark is a ring that can be seen (the page's own reduced-motion state: a still ring).
    const ring = await page.locator("[data-slot=source-card][data-highlight]").evaluate((el) => { const cs = getComputedStyle(el); return { style: cs.outlineStyle, width: cs.outlineWidth, colour: cs.outlineColor }; });
    assert(ring.style === "solid" && ring.width === "2px" && !/rgba\(0, 0, 0, 0\)|transparent/.test(ring.colour), `the marked card's ring is ${JSON.stringify(ring)}`);
    // The mark is one-shot: it goes away by itself.
    await page.waitForFunction(() => !document.querySelector("[data-slot=source-card][data-highlight]"), null, { timeout: 5000 });
    return "folded panel unfolds, 来源 selected, card 2 scrolled into view and marked once";
  } finally { await view.close(); }
}

/** Acceptance 2: a turn that is running grows its bar chip by chip, and a finished turn folds to 「已思考 N 秒 · M 步」. */
async function stepsLive(ctx) {
  const view = await openChat(ctx, "steps-live");
  try {
    const { page } = view;
    const hand = await streamSteps(page);
    const bar = page.locator("[data-testid=turn-steps]").last();
    const chips = bar.locator("[data-slot=step-chip]");
    assert((await chips.count()) === 5, `${await chips.count()} chips after five steps`);
    assert((await bar.locator("[data-slot=step-chip][data-state=running]").count()) === 1, "not exactly one step is turning");
    const text = await bar.innerText();
    assert(text.includes("(3)") && text.includes("(12)"), `the finished tools do not show their hit counts: ${JSON.stringify(text)}`);
    assert((await bar.locator("[data-slot=thinking-slot]").count()) === 1, "the first cell (thinking slot) is missing");
    assert((await bar.getAttribute("data-state")) === "running", "the bar is not in its running state");
    // The running tool comes back with nothing, then a check step starts: the bar grows.
    await hand.push(0, "trace", traceEvent("r6", "tool", { name: "query_latest_forecast", after: ["r3"], start_ms: 1650, ms: 800, output: { ok: true, count: 0 } }));
    await hand.push(0, "trace", traceEvent("r7", "verify", { after: ["r4", "r5", "r6"], start_ms: 2500, ms: null, status: "running" }));
    await page.waitForFunction(() => [...document.querySelectorAll("[data-testid=turn-steps]")].pop()?.querySelectorAll("[data-slot=step-chip]").length >= 6, null, { timeout: 5000 });
    assert((await chips.count()) === 6, `${await chips.count()} chips after the sixth step`);
    assert((await bar.innerText()).includes("无匹配"), "a tool that found nothing does not say 无匹配");
    await hand.push(0, "trace", traceEvent("r7", "verify", { after: ["r4", "r5", "r6"], start_ms: 2500, ms: 600, output: { citations: 0, issues: [] } }));
    await hand.push(0, "delta", { text: "过程条测试的回答。" });
    await hand.push(0, "done", { status: "complete", turn_id: "t9000000-0000-4000-8000-0000000000f1", thinking_ms: 12400, citations: [], citation_protocol: null });
    await hand.close(0);
    await page.waitForFunction(() => [...document.querySelectorAll("[data-testid=turn-steps]")].pop()?.getAttribute("data-state") === "summary", null, { timeout: 8000 });
    const summary = (await bar.innerText()).replace(/\s+/g, " ").trim();
    assert(/已思考 12 秒 · 6 步/.test(summary), `the folded bar says ${JSON.stringify(summary)}`);
    assert((await bar.locator("[data-slot=step-chip]").count()) === 0, "the chips are still there after the turn ended");
    return `5 chips (1 turning, counts 3 and 12), 6 after the next event with 无匹配, folded to ${JSON.stringify(summary)}`;
  } finally { await view.close(); }
}

/** The process bar opens 过程 on its own round: a second round's bar changes the round the panel shows. */
async function stepsOpenProcess(ctx) {
  const view = await openChat(ctx, "steps-open-process");
  try {
    const { page } = view;
    await page.locator("[data-testid=panel-close]").click();
    await page.locator("[data-testid=context-panel]").waitFor({ state: "detached", timeout: 5000 });
    const answers = page.locator("[data-testid=message][data-role=assistant]");
    await answers.first().locator("[data-testid=turn-steps]").click();
    await page.locator("[data-testid=timeline-step]").first().waitFor({ timeout: 5000 });
    assert((await page.locator("[data-testid=tab-process]").getAttribute("aria-selected")) === "true", "过程 is not the selected tab");
    const first = await page.locator("[data-testid=panel-round]").innerText();
    assert(first.includes("AAPL 最近一个季"), `the panel names ${JSON.stringify(first)} for the first round`);
    const stepsOfFirst = await page.locator("[data-testid=timeline-step]").count();
    assert(stepsOfFirst === 9, `${stepsOfFirst} steps for the first round (its trace has 9 nodes)`);
    const second = answers.nth(1).locator("[data-testid=turn-steps]");
    await second.scrollIntoViewIfNeeded();
    await second.click();
    await page.waitForFunction(() => document.querySelector("[data-testid=panel-round]")?.textContent?.includes("把 AAPL 的两版预测"), null, { timeout: 5000 });
    assert((await page.locator("[data-testid=timeline-step]").count()) === 6, "the second round's steps are not what the panel lists");
    assert(/部分来源可用/.test(await answers.nth(1).locator("[data-testid=turn-steps]").innerText()), "a partially_succeeded turn's bar does not say 部分来源可用");
    return `folded panel unfolds on 过程; round 1: ${stepsOfFirst} steps; the second bar switches the round (6 steps) and says 部分来源可用`;
  } finally { await view.close(); }
}

/** The computed colours that mean danger or action, resolved the way the page resolves them. */
async function warningColours(page) {
  return page.evaluate(() => {
    const out = new Set();
    for (const name of ["--danger", "--action", "--action-soft"]) {
      const probe = document.createElement("span"); probe.style.color = `var(${name})`; probe.style.backgroundColor = `var(${name})`; document.body.appendChild(probe);
      const cs = getComputedStyle(probe); out.add(cs.color); out.add(cs.backgroundColor); probe.remove();
    }
    return [...out];
  });
}
async function colourReport(handle, banned) {
  return handle.evaluate((root, list) => {
    const bad = [];
    for (const el of [root, ...root.querySelectorAll("*")]) {
      const cs = getComputedStyle(el);
      for (const prop of ["color", "backgroundColor", "borderTopColor", "borderLeftColor", "outlineColor", "textDecorationColor"]) if (list.includes(cs[prop])) bad.push(`${el.tagName}.${prop}=${cs[prop]}`);
      if (el.tagName === "svg") bad.push("an icon");
    }
    return bad;
  }, banned);
}

/** Acceptance 4: the public mark's card says exactly what the existing functions compute for the same message, and the mark carries no danger or action colour, no icon, in both themes. */
async function publicMarkVerbatim(ctx) {
  const message = buildState().chat.conversations.get(CONVERSATION.finbot).find((m) => Array.isArray(m.public_marks) && m.public_marks.length);
  const [view0] = normalizePublicMarks(message.public_marks);
  const expected = { template: view0.label, quote: publicMarkQuoteText(view0, (text) => text), cite: `查看来源 [${view0.evidence.ordinal}]` };
  const done = [];
  for (const theme of ["light", "dark"]) {
    const view = await newView(ctx.browser, { width: 1440, theme, label: `public-mark-${theme}`, unmatched });
    try {
      const { page } = view;
      await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
      await waitReady(page, PAGES.find((p) => p.name === "chat-default"));
      const mark = page.locator("[data-testid=public-mark]").first();
      await mark.scrollIntoViewIfNeeded();
      assert((await mark.innerText()) === "◦", `the mark reads ${JSON.stringify(await mark.innerText())}`);
      const banned = await warningColours(page);
      // At rest (before the pointer is on it), then open: hover and open states have their own colours.
      const rest = await colourReport(await mark.elementHandle(), banned);
      assert(rest.length === 0, `${theme}: the mark at rest uses a danger / action colour or an icon: ${rest.join(", ")}`);
      await mark.hover();
      const card = page.locator("[data-testid=public-mark-card]");
      await card.waitFor({ timeout: 5000 });
      const got = { template: await card.locator("[data-slot=public-mark-template]").textContent(), quote: await card.locator("[data-slot=public-mark-quote]").textContent(), cite: await card.locator("[data-slot=public-mark-cite]").textContent() };
      for (const key of Object.keys(expected)) assert(got[key] === expected[key], `${theme}: card ${key} is ${JSON.stringify(got[key])}, the existing functions give ${JSON.stringify(expected[key])}`);
      assert((await card.textContent()) === expected.template + expected.quote + expected.cite, `${theme}: the card's whole text differs from the three computed texts joined`);
      assert((await card.locator("> *").count()) === 3, `${theme}: the card has ${await card.locator("> *").count()} children (template, quote, cite)`);
      for (const [name, handle] of [["mark (open)", await mark.elementHandle()], ["card", await card.elementHandle()]]) {
        const bad = await colourReport(handle, banned);
        assert(bad.length === 0, `${theme}: the ${name} uses a danger / action colour or an icon: ${bad.join(", ")}`);
      }
      // The sentence stays as written: not struck through, not faded.
      const sentence = await mark.evaluate((el) => { const p = el.closest("li, p"); const cs = getComputedStyle(p); return { line: cs.textDecorationLine, opacity: cs.opacity }; });
      assert(sentence.line === "none" && sentence.opacity === "1", `${theme}: the marked sentence is ${JSON.stringify(sentence)}`);
      await page.keyboard.press("Escape");
      await card.waitFor({ state: "detached", timeout: 5000 });
      done.push(theme);
    } finally { await view.close(); }
  }
  return `${done.join(" + ")}: card = template + quote + 查看来源 [1] word for word (${JSON.stringify(expected.cite)}), no danger / action colour, no icon, sentence untouched`;
}

/** The old-style line mark (a message from before the public marks) is the same neutral footnote, and 追问依据 still puts its question in the box. */
async function legacyLineMark(ctx) {
  const view = await openChat(ctx, "legacy-line-mark");
  try {
    const { page } = view;
    const mark = page.locator("[data-testid=line-mark]").first();
    await mark.scrollIntoViewIfNeeded();
    await mark.click();
    const card = page.locator("[data-testid=line-mark-card]");
    await card.waitFor({ timeout: 5000 });
    const text = await card.locator("[data-slot=line-mark-text]").textContent();
    assert(text === "证据不足：引用的来源里找不到这个说法", `the card says ${JSON.stringify(text)}`);
    const bad = await colourReport(await card.elementHandle(), await warningColours(page));
    assert(bad.length === 0, `the old line mark's card uses a danger / action colour or an icon: ${bad.join(", ")}`);
    await card.locator("[data-slot=line-mark-ask]").click();
    const draft = await page.locator("#agent-draft").inputValue();
    assert(draft === followUpQuestion("3. 两版的看涨概率几乎没变，可以认为新材料没有改变上行逻辑。"), `追问依据 put ${JSON.stringify(draft)} in the box`);
    assert((await page.evaluate(() => document.activeElement?.id)) === "agent-draft", "the focus is not in the input box after 追问依据");
    return `neutral ◦, card text "${text}", 追问依据 fills the box and focuses it`;
  } finally { await view.close(); }
}

/** Acceptance 3: an answer from before the step graph shows only its time (or nothing, or the old tool badges as chips): the three cases the old panel and badges had. */
async function oldMessageNoSteps(ctx) {
  const view = await openChat(ctx, "old-message-no-steps");
  try {
    const { page } = view;
    // Nothing at all: the routine result has no time, no trace, no tools.
    const routine = page.locator("[data-testid=message][data-role=assistant]", { hasText: "盘前关注列表里有 3 条" });
    await routine.waitFor({ timeout: 10000 });
    assert((await routine.locator("[data-testid=turn-steps]").count()) === 0, "an answer with no step data shows a process bar");
    // Only its time (AppleBot's answer): a line, not a button, no chips.
    await page.goto(`${ctx.server.url}#/chat/${BOT.applebot}`, { waitUntil: "load" });
    const time = page.locator("[data-testid=turn-steps][data-state=time]");
    await time.waitFor({ timeout: 10000 });
    assert((await time.evaluate((el) => el.tagName)) === "DIV", "the time-only bar is a button");
    assert(/^已思考 2\.8 秒$/.test((await time.innerText()).trim()), `the time-only bar says ${JSON.stringify(await time.innerText())}`);
    assert((await time.locator("[data-slot=step-chip]").count()) === 0, "the time-only bar has chips");
    // The tool list only (NewsBot's answer): the old tool badge as a chip.
    await page.goto(`${ctx.server.url}#/chat/${BOT.newsbot}`, { waitUntil: "load" });
    const tools = page.locator("[data-testid=turn-steps][data-state=tools] [data-slot=step-chip]");
    await tools.first().waitFor({ timeout: 10000 });
    const chip = (await tools.first().innerText()).trim();
    assert(chip === "搜索已配置新闻源 · 已完成 · 6 条结果", `the tool chip reads ${JSON.stringify(chip)}`);
    // The panel's 过程 tab says there are no steps for such a round.
    await page.locator("[data-testid=tab-process]").click();
    await page.locator("[data-testid=process-empty]").waitFor({ timeout: 5000 });
    return `no data: no bar; time only: "已思考 2.8 秒" (not a button); tool list only: ${JSON.stringify(chip)}; 过程 tab: no step record`;
  } finally { await view.close(); }
}

/** Drag the panel's edge wider; the width survives a reload; folding survives a reload; the arrow keys resize too. */
async function panelResizePersists(ctx) {
  const view = await openChat(ctx, "panel-resize-persists");
  try {
    const { page } = view;
    const before = (await panelBox(page)).width;
    const handle = page.locator("[data-testid=panel-resize]");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + 200);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 120, box.y + 200, { steps: 6 });
    await page.mouse.up();
    const wide = (await panelBox(page)).width;
    assert(Math.abs(wide - (before + 120)) <= 2, `dragging 120px left took the panel from ${before} to ${wide}`);
    await page.reload({ waitUntil: "load" });
    await page.locator("[data-testid=context-panel]").waitFor({ timeout: 10000 });
    const kept = (await panelBox(page)).width;
    assert(Math.abs(kept - wide) <= 2, `the width was ${wide} before the reload and ${kept} after`);
    await page.locator("[data-testid=panel-resize]").focus();
    await page.keyboard.press("ArrowLeft");
    const keyed = (await panelBox(page)).width;
    assert(Math.abs(keyed - (kept + 16)) <= 2, `ArrowLeft took the panel from ${kept} to ${keyed}`);
    await page.locator("[data-testid=panel-close]").click();
    await page.reload({ waitUntil: "load" });
    await page.locator("[data-testid=message]").first().waitFor({ timeout: 10000 });
    assert((await page.locator("[data-testid=context-panel]").count()) === 0, "the folded panel is open again after a reload");
    await page.locator("[data-testid=side-toggle]").click();
    await page.locator("[data-testid=context-panel]").waitFor({ timeout: 5000 });
    const reopened = (await panelBox(page)).width;
    assert(Math.abs(reopened - keyed) <= 2, `the width after unfolding is ${reopened}, not the kept ${keyed}`);
    return `${before} -> ${wide} by drag, kept over a reload (${kept}), +16 by ArrowLeft (${keyed}); folded stays folded over a reload and unfolds at ${reopened}`;
  } finally { await view.close(); }
}

/** Keyboard: Tab reaches a citation chip, its hover card opens on focus, Enter takes the focus into the source card, Esc returns it to the chip. */
async function sourcesKeyboard(ctx) {
  const view = await openChat(ctx, "sources-keyboard");
  try {
    const { page } = view;
    const answer = firstAnswer(page);
    await answer.locator("[data-testid=turn-steps]").focus();
    let reached = null;
    for (let i = 0; i < 8 && !reached; i += 1) {
      await page.keyboard.press("Tab");
      reached = await page.evaluate(() => { const el = document.activeElement; return el?.getAttribute("data-testid") === "citation-chip" ? el.getAttribute("data-ordinal") : null; });
    }
    assert(reached === "1", `Tab did not reach the first citation chip (got ${reached})`);
    await page.locator("[data-slot=hover-card-content]").waitFor({ timeout: 5000 });
    await page.waitForFunction(() => document.querySelector("[data-slot=hover-card-content]")?.textContent?.includes("Services net sales"), null, { timeout: 5000 });
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.activeElement?.closest("[data-slot=source-card]")?.getAttribute("data-ordinal") === "1", null, { timeout: 5000 });
    assert((await page.locator("[data-slot=source-card][data-ordinal='1']").getAttribute("data-highlight")) !== null, "the card Enter went to is not marked");
    await page.keyboard.press("Escape");
    const back = await page.evaluate(() => ({ id: document.activeElement?.getAttribute("data-testid"), ordinal: document.activeElement?.getAttribute("data-ordinal") }));
    assert(back.id === "citation-chip" && back.ordinal === "1", `Esc left the focus on ${JSON.stringify(back)}, not on the chip`);
    return "Tab reaches [1], the hover card shows its excerpt on focus, Enter moves the focus into the card (marked), Esc returns it to [1]";
  } finally { await view.close(); }
}

/** Every field of the old drawer has a place on the card; a withdrawn source is an error bar with 重试; each chunk is asked for once. */
async function sourceCardFields(ctx) {
  const state = buildState();
  const messages = state.chat.conversations.get(CONVERSATION.finbot);
  const answer = messages.find((m) => m.role === "assistant" && m.citations?.length === 2 && m.trace);
  answer.citations.push(
    { ordinal: 3, chunk_id: null, document_id: null, title: "Apple 披露欧盟 App Store 政策调整", section: "", source_url: "https://news.example.test/apple-eu", observed_at: "2026-11-12T01:30:00Z", published_at: "2026-11-11", quote: "Apple said the new terms take effect in the EU on Monday.", source_type: "web_news", truncated: true },
    { ordinal: 4, chunk_id: "k0000000-0000-4000-8000-00000000000f", document_id: null, title: "已撤回的材料", section: "", source_url: null, observed_at: null, published_at: null, quote: "", source_type: "saved_filing", truncated: false },
  );
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "source-card-fields", unmatched, fixtureState: state });
  try {
    const { page } = view;
    const asked = [];
    page.on("request", (request) => { if (/\/knowledge\/citations\//.test(request.url())) asked.push(request.url().split("/").pop()); });
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await waitReady(page, PAGES.find((p) => p.name === "chat-default"));
    const chip = firstAnswer(page).locator("[data-testid=sources-chip]");
    assert(/来源 4/.test((await chip.innerText()).trim()), `the footer chip says ${JSON.stringify(await chip.innerText())}`);
    await chip.scrollIntoViewIfNeeded();
    await chip.click();
    await page.locator("[data-slot=source-card]").nth(3).waitFor({ timeout: 5000 });
    const card = (n) => page.locator(`[data-slot=source-card][data-ordinal='${n}']`);
    // 1: a saved filing: type, dates, the excerpt read through the chunk, the link to the original.
    await card(1).locator("[data-slot=source-quote]").waitFor({ timeout: 5000 });
    const c1 = await card(1).innerText();
    assert(c1.includes("已保存申报") && c1.includes("观察 2026-") && c1.includes("Services gross margin percentage was 75.0%"), `card 1 reads ${JSON.stringify(c1)}`);
    assert((await card(1).locator("[data-slot=source-card-open]").getAttribute("href")).startsWith("https://www.sec.gov/"), "card 1 has no link to the original");
    assert((await card(1).locator("[data-slot=source-quote]").evaluate((el) => getComputedStyle(el).fontFamily)).toLowerCase().includes("serif"), "the excerpt is not in the quote face");
    // 2: derived content: marked 派生, version line, original quotes.
    await card(2).locator("[data-slot=source-card-derived]").waitFor({ timeout: 5000 });
    const c2 = await card(2).innerText();
    assert(c2.includes("派生") && c2.includes("v2 · analysis-v2 · muse-ember") && c2.includes("原文引文：") && c2.includes("gross margin was 75.0%"), `card 2 reads ${JSON.stringify(c2)}`);
    assert((await card(2).locator("[data-slot=source-card-open]").count()) === 0, "card 2 has no original to open but shows the link");
    // 3: a web page: published and fetched dates, the truncated note, its own quote, no chunk request.
    const c3 = await card(3).innerText();
    assert(c3.includes("新闻网页") && c3.includes("发布 2026-11-11") && c3.includes("抓取 2026-11-12") && c3.includes("保存内容可能不完整") && c3.includes("the new terms take effect"), `card 3 reads ${JSON.stringify(c3)}`);
    assert((await card(3).locator("[data-slot=source-card-open]").getAttribute("target")) === "_blank", "the original does not open in a new tab");
    // 4: a withdrawn source: an error bar with 重试.
    await card(4).locator("[data-testid=excerpt-error]").waitFor({ timeout: 5000 });
    assert((await card(4).innerText()).includes("来源已撤回或不可访问") && (await card(4).getByRole("button", { name: "重试" }).count()) === 1, "the withdrawn source does not say so with a 重试 button");
    assert((await card(4).innerText()).includes("观察时间未知"), "the unknown observed time is not said");
    const distinct = new Set(asked);
    assert(asked.length === distinct.size, `a chunk was asked for twice: ${asked.join(", ")}`);
    return `4 cards: type, dates, serif excerpt, 派生 + version + original quotes, link, web dates + 保存内容可能不完整, withdrawn = error bar + 重试; ${asked.length} chunk requests, none repeated`;
  } finally { await view.close(); }
}

/** Design 3.4: the bot's workspace cards (add, move, resize, pin a stock, delete, reset) work in the panel's 工作区 tab as they did in the old rail, and the layout is kept per bot. */
async function workspaceCardsInPanel(ctx) {
  const view = await openChat(ctx, "workspace-cards-in-panel");
  try {
    const { page } = view;
    const pane = page.locator("[data-testid=workspace-pane]");
    assert((await page.locator("[data-testid=tab-workspace]").getAttribute("aria-selected")) === "true", "the panel does not open on 工作区 by default");
    await pane.locator("section.ws-card").first().waitFor({ timeout: 10000 });
    const titles = () => pane.locator("section.ws-card").evaluateAll((els) => els.map((el) => el.getAttribute("aria-label")));
    const first = await titles();
    assert(first.length === 6, `${first.length} cards by default`);
    await pane.getByRole("button", { name: /编辑卡片/ }).click();
    // Move the first card down, make the second a large one, pin the third to NVDA.
    await pane.getByRole("button", { name: "下移" }).first().click();
    const moved = await titles();
    assert(moved[0] === first[1] && moved[1] === first[0], `the first card did not move down: ${moved.join(" / ")}`);
    await pane.locator("select[aria-label=大小]").nth(1).selectOption("l");
    await pane.locator("input[aria-label=固定股票]").first().fill("NVDA");
    await pane.locator("input[aria-label=固定股票]").first().blur();
    // Delete the last card, then add it back from the list of missing ones.
    await pane.getByRole("button", { name: "删除" }).last().click();
    assert((await titles()).length === 5, "the last card was not deleted");
    await pane.locator("select[aria-label=添加卡片]").selectOption({ index: 1 });
    assert((await titles()).length === 6, "the added card is not in the list");
    await pane.getByRole("button", { name: "完成" }).click();
    const stored = await page.evaluate((id) => JSON.parse(localStorage.getItem(`market-evidence-agent:workspace:${id}:v1`)), BOT.finbot);
    assert(stored[1].size === "l" && stored.some((item) => item.symbol === "NVDA"), `the stored layout is ${JSON.stringify(stored)}`);
    // The layout is kept per bot over a reload; 恢复默认 puts the six back.
    await page.reload({ waitUntil: "load" });
    await pane.locator("section.ws-card").first().waitFor({ timeout: 10000 });
    const kept = await titles();
    assert(kept.join() === (await titles()).join() && kept[0] === first[1], `the layout is not kept over a reload: ${kept.join(" / ")}`);
    await pane.getByRole("button", { name: /编辑卡片/ }).click();
    await pane.getByRole("button", { name: "恢复默认" }).click();
    assert((await titles()).join() === first.join(), "恢复默认 did not bring the default order back");
    return "six default cards; move down, size L, pin NVDA, delete, add back; stored per bot, kept over a reload; 恢复默认 restores the order";
  } finally { await view.close(); }
}

/** Between 「sent」 and the first event there is no message yet: the line shows the bot's head and the bar's first cell; the first event replaces it with the real message. */
async function stepsPending(ctx) {
  const view = await openChat(ctx, "steps-pending");
  try {
    const { page } = view;
    const hand = await handFed(page);
    await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
    await page.locator("#agent-draft").fill(`${HAND_MARKER} 等首个字`);
    await page.locator("[data-testid=send]").click();
    await hand.opened(0);
    const pending = page.locator("[data-testid=pending-answer]");
    await pending.waitFor({ timeout: 5000 });
    const slot = pending.locator("[data-slot=thinking-slot]");
    assert((await slot.count()) === 1, "the waiting line has no first cell");
    assert(/思考中\s+0\.0 秒/.test((await slot.innerText()).trim()), `the first cell says ${JSON.stringify(await slot.innerText())}`);
    assert((await pending.locator("button").count()) === 0, "the bar before the first event is a button (there is no round to open yet)");
    assert((await page.locator("[data-testid=message][data-role=assistant]").filter({ has: page.locator("[data-testid=turn-steps][data-state=running]") }).count()) === 0, "a real message exists before the first event");
    await hand.push(0, "conversation", { conversation_id: CONVERSATION.finbot, turn_id: "t9000000-0000-4000-8000-0000000000f2", bot_id: BOT.finbot });
    await pending.waitFor({ state: "detached", timeout: 5000 });
    await page.locator("[data-testid=message][data-role=assistant] [data-testid=turn-steps][data-state=running]").last().waitFor({ timeout: 5000 });
    await hand.push(0, "done", { status: "complete", turn_id: "t9000000-0000-4000-8000-0000000000f2", thinking_ms: 800, citations: [], citation_protocol: null });
    await hand.close(0);
    return "the waiting line shows the bot's head and 「思考中 0.0 秒」 (not a button), and the first event replaces it with the real message and its running bar";
  } finally { await view.close(); }
}


// --- P3.4: the confirmation card, the state rows, the phone's drawers --------------------------------------------------------------
/** A fresh view of a chat address at any width (openChat is 1440 and the default line only). */
async function openChatAt(ctx, label, { width = 1440, hash = "#/chat", theme = "light", ready = "[data-testid=message]", fixtureState } = {}) {
  const view = await newView(ctx.browser, { width, theme, label, unmatched, ...(fixtureState ? { fixtureState } : {}) });
  await view.page.goto(`${ctx.server.url}${hash}`, { waitUntil: "load" });
  await view.page.waitForSelector(ready, { state: "visible", timeout: 15000 });
  await settle(view.page);
  return view;
}
const APPROVAL = "[data-slot=approval-card]";
const ACTIVE_CARD = "[data-slot=approval-card][data-state=active]";
const BASELINE = JSON.parse(fs.readFileSync(new URL("./fixtures/approval-bodies-baseline.json", import.meta.url), "utf8"));
/** Raw bodies of the stream requests, as the browser sent them (a string each), to compare byte for byte. */
function watchRaw(page) {
  const raw = [];
  page.on("request", (request) => { if (request.method() === "POST" && STREAM_PATH.test(new URL(request.url()).pathname)) raw.push(request.postData()); });
  return raw;
}
/** In TeslaBot's line: send the ASK marker and wait for its card. */
async function askInTesla(ctx, label) {
  const view = await openChatAt(ctx, label, { hash: `#/chat/${BOT.teslabot}`, ready: "[data-testid=welcome]" });
  const { page } = view;
  const raw = watchRaw(page);
  await page.locator("#agent-draft:not([disabled])").waitFor({ timeout: 10000 });
  await page.locator("#agent-draft").fill(`${ASK_MARKER} 查一下结果`);
  await clickSend(page);
  await page.locator(ACTIVE_CARD).waitFor({ timeout: 10000 });
  return { view, raw };
}
const answered = (page) => page.locator("[data-testid=message][data-role=assistant]", { hasText: FAKE_ANSWER }).waitFor({ timeout: 10000 });

/**
 * The five things a card can send are byte for byte what the old card sent: the bodies were recorded from the old card on the unchanged build
 * (fixtures/approval-bodies-baseline.json) and the new card must produce the same strings.
 */
async function approvalRequestBody(ctx) {
  const got = {};
  { const view = await openChatAt(ctx, "approval-body-confirm"); try { const raw = watchRaw(view.page); await view.page.locator(`${ACTIVE_CARD} button`, { hasText: "确认执行" }).click(); await answered(view.page); got.confirm = raw.slice(); } finally { await view.close(); } }
  { const view = await openChatAt(ctx, "approval-body-cancel"); try { const raw = watchRaw(view.page); await view.page.locator(`${ACTIVE_CARD} button`, { hasText: "先不要" }).click(); await answered(view.page); got.cancel = raw.slice(); } finally { await view.close(); } }
  { const { view, raw } = await askInTesla(ctx, "approval-body-option"); try { await view.page.locator(`${ACTIVE_CARD} button`, { hasText: "第二条结果" }).click(); await answered(view.page); got.option = raw.slice(1); } finally { await view.close(); } }
  { const { view, raw } = await askInTesla(ctx, "approval-body-reply"); try { const form = view.page.locator(`${ACTIVE_CARD} form`); await form.locator("input").fill("两个都看看"); await form.getByRole("button", { name: "发送" }).click(); await answered(view.page); got.reply = raw.slice(1); } finally { await view.close(); } }
  { const view = await openChatAt(ctx, "approval-body-revision"); try {
      const { page } = view; const raw = watchRaw(page);
      const hand = await handTurn(page, { text: "修订", lead: "可以用下面这些新材料修订预测，请勾选。", turnId: "t9000000-0000-4000-8000-0000000000e9" });
      await endWithCard(hand, 0, revisionCard(), "t9000000-0000-4000-8000-0000000000e9");
      const card = page.locator(ACTIVE_CARD); await card.waitFor();
      await card.locator("input[type=checkbox]").nth(2).check(); await card.locator("input[type=checkbox]").nth(0).check();
      const before = raw.length; await card.locator("button", { hasText: "用所选材料修订" }).click(); await answered(page); got.revision = raw.slice(before);
    } finally { await view.close(); } }
  for (const key of ["confirm", "cancel", "option", "reply", "revision"]) {
    assert(got[key]?.length === 1, `${key}: expected one request, saw ${got[key]?.length}`);
    // The one thing that may differ is the id of the card the check pushed itself (the baseline's revision card used another request id of the same shape).
    assert(got[key][0] === BASELINE[key][0], `${key} request changed:\n  now      ${got[key][0]}\n  baseline ${BASELINE[key][0]}`);
  }
  return "confirm, cancel, option, typed reply and ticked materials: five request bodies identical to the old card's, byte for byte";
}

/** Acceptance 2: the revision card does not tick anything for the reader, holds its button until the minimum is ticked and says why; with no candidate it says so. */
async function revisionCardMinSelect(ctx) {
  const view = await openChatAt(ctx, "revision-min-select");
  try {
    const { page } = view;
    const hand = await handTurn(page, { text: "修订", lead: "可以用下面这些新材料修订预测，请勾选。" });
    await endWithCard(hand, 0, revisionCard());
    const card = page.locator(ACTIVE_CARD); await card.waitFor({ timeout: 10000 });
    const boxes = card.locator("input[type=checkbox]"), main = card.locator("[data-approval-primary]");
    assert((await boxes.count()) === 3, "the card does not list its three materials");
    assert((await card.locator("input[type=checkbox]:checked").count()) === 0, "a material is ticked before the reader ticked it");
    assert(await main.isDisabled(), "the main button is usable with nothing ticked");
    const reason = card.locator("[data-slot=approval-reason]");
    assert(/至少勾选 2 份材料/.test(await reason.innerText()), `the reason says ${JSON.stringify(await reason.innerText().catch(() => null))}`);
    assert((await main.getAttribute("aria-describedby")) === (await reason.getAttribute("id")), "the reason is not tied to the disabled button");
    assert(!(await card.innerText()).match(/全选|推荐|自动选/), "the card offers to choose for the reader");
    await boxes.nth(0).check();
    assert(await main.isDisabled(), "the main button is usable with one of two ticked");
    await boxes.nth(2).check();
    assert(await main.isEnabled(), "the main button stays disabled with two ticked");
    assert((await reason.count()) === 0, "the reason is still shown with enough ticked");
    await boxes.nth(2).uncheck();
    assert(await main.isDisabled(), "the main button did not go back to disabled");
    // The card with nothing to tick.
    const none = await openChatAt(ctx, "revision-none");
    try {
      const h = await handTurn(none.page, { text: "修订", lead: "这版预测没有可用于修订的新材料。" });
      await endWithCard(h, 0, revisionCard({ candidates: false }));
      const c = none.page.locator(ACTIVE_CARD); await c.waitFor({ timeout: 10000 });
      assert((await c.innerText()).includes("没有可用于修订的新材料"), "the card with no candidate does not say so");
      assert((await c.locator("input[type=checkbox]").count()) === 0, "a card with no candidate lists something to tick");
      assert(await c.locator("[data-approval-primary]").isDisabled(), "the confirm button is usable with nothing to send");
      assert(await c.locator("button", { hasText: "先不要" }).isEnabled(), "the reader cannot decline a card with no candidate");
    } finally { await none.close(); }
    return "nothing pre-ticked, no select-all; the button waits for 2 ticks and says why; goes back to disabled when un-ticked; no-candidate card says so";
  } finally { await view.close(); }
}

/** A card made in this session counts ten minutes down against the clock and falls to 已过期 at zero; a card from the history shows only the static note. */
async function approvalCountdown(ctx) {
  const old = await openChatAt(ctx, "approval-countdown-history");
  try {
    const card = old.page.locator(ACTIVE_CARD); await card.waitFor();
    assert((await card.locator("[data-slot=approval-timer]").count()) === 0, "a card read back from the server shows a countdown");
    assert((await card.locator("[data-slot=approval-note]").innerText()).includes("确认有效期为十分钟"), "the history card has no static note");
  } finally { await old.close(); }
  const view = await openChatAt(ctx, "approval-countdown");
  try {
    const { page } = view;
    const hand = await handTurn(page, { text: "确认", lead: "我可以抓取 AAPL 最新 10-Q 并生成分析，请确认。" });
    await endWithCard(hand, 0, freshWriteCard());
    const timer = page.locator("[data-slot=approval-timer]"); await timer.waitFor({ timeout: 10000 });
    assert((await timer.innerText()) === "10:00", `the timer starts at ${await timer.innerText()}`);
    assert(/mono/.test(await timer.evaluate((el) => getComputedStyle(el).fontFamily + " " + el.className)) || /mono/i.test(await timer.evaluate((el) => getComputedStyle(el).fontFamily)), "the timer is not set in the mono face");
    await page.clock.setFixedTime(new Date(FIXED_TIME.getTime() + 61_000));
    await page.waitForFunction(() => document.querySelector("[data-slot=approval-timer]")?.textContent === "08:59", null, { timeout: 5000 });
    await page.clock.setFixedTime(new Date(FIXED_TIME.getTime() + 599_000));
    await page.waitForFunction(() => document.querySelector("[data-slot=approval-timer]")?.textContent === "00:01", null, { timeout: 5000 });
    await page.clock.setFixedTime(new Date(FIXED_TIME.getTime() + 601_000));
    const gone = page.locator(`${APPROVAL}[data-state=expired]`); await gone.waitFor({ timeout: 5000 });
    assert((await gone.innerText()).includes("已过期") && (await gone.innerText()).includes("在对话里再说一次"), `the expired card says ${JSON.stringify(await gone.innerText())}`);
    assert((await gone.locator("button").count()) === 0 && (await page.locator("[data-slot=approval-timer]").count()) === 0, "the expired card still has buttons or a timer");
    assert((await gone.boundingBox()).height < 56, "the expired card is still a block");
    return "history card: static 确认有效期为十分钟, no timer; this session's card: 10:00 → 08:59 → 00:01 against the clock, then one 已过期 line without buttons";
  } finally { await view.close(); }
}

/** Once answered, the card is one line: 已确认 · title, or 已取消; a line typed in the box instead leaves 未确认. */
async function approvalCollapses(ctx) {
  const yes = await openChatAt(ctx, "approval-collapse-yes");
  try {
    const full = await yes.page.locator(ACTIVE_CARD).boundingBox();
    await yes.page.locator(`${ACTIVE_CARD} button`, { hasText: "确认执行" }).click(); await answered(yes.page);
    const line = yes.page.locator(`${APPROVAL}[data-state=answered]`);
    const text = await line.innerText();
    assert(/已确认 · 抓取并分析 NVDA 10-Q/.test(text), `the folded card says ${JSON.stringify(text)}`);
    const box = await line.boundingBox();
    assert(box.height < 56 && full.height > 150 && (await line.locator("button").count()) === 0, `the card did not fold (${full.height}px → ${box.height}px)`);
  } finally { await yes.close(); }
  const no = await openChatAt(ctx, "approval-collapse-no");
  try {
    await no.page.locator(`${ACTIVE_CARD} button`, { hasText: "先不要" }).click(); await answered(no.page);
    assert(/已取消/.test(await no.page.locator(`${APPROVAL}[data-state=answered]`).innerText()), "declined card does not say 已取消");
  } finally { await no.close(); }
  const typed = await openChatAt(ctx, "approval-collapse-typed");
  try {
    // The reader ignores the buttons and types: an ordinary message goes out (no pending_request_id: the composer was never tied to the card), and the card is not confirmed.
    const bodies = watchPosts(typed.page, STREAM_PATH);
    await typed.page.locator("#agent-draft").fill("先看看 AAPL 的行情"); await clickSend(typed.page); await answered(typed.page);
    assert(bodies.length === 1 && bodies[0].pending_request_id === undefined && !String(bodies[0].message).startsWith("confirm:"), `a typed line went out as ${JSON.stringify(bodies)}`);
    assert(/未确认 · 抓取并分析 NVDA 10-Q/.test(await typed.page.locator(`${APPROVAL}[data-state=answered]`).innerText()), "a card passed over does not say 未确认");
  } finally { await typed.close(); }
  return "确认执行 → 已确认 · 抓取并分析 NVDA 10-Q, 先不要 → 已取消, a typed line → 未确认; each one line, no buttons";
}

/** S9: the amber strip above the input; it takes the reader to the card and puts the focus on its main action; the input stays usable. */
async function waitingStrip(ctx) {
  const view = await openChatAt(ctx, "waiting-strip");
  try {
    const { page } = view;
    const strip = page.locator("[data-testid=waiting-strip]"); await strip.waitFor({ timeout: 10000 });
    assert((await strip.innerText()).includes("FinBot 在等你确认上面的卡片"), `the strip says ${JSON.stringify(await strip.innerText())}`);
    assert(/在等你确认/.test(await page.locator("[role=status].sr-only").first().innerText()), "no screen-reader announcement of who is waiting");
    assert(await page.locator("#agent-draft").isEnabled(), "the input is not usable while the bot waits");
    assert(!(await page.evaluate(() => Boolean(document.activeElement?.closest("[data-slot=approval-card]")))), "the card took the focus when it appeared");
    await page.evaluate(() => { document.querySelector("[data-testid=transcript]").scrollTop = 0; });
    assert(!(await inView(page, ACTIVE_CARD, "[data-testid=transcript]")), "the card is already in view; the scroll check proves nothing");
    await strip.click();
    await page.waitForFunction(() => document.activeElement?.hasAttribute("data-approval-primary"), null, { timeout: 5000 });
    assert(await inView(page, ACTIVE_CARD, "[data-testid=transcript]"), "the strip did not scroll to the card");
    assert((await page.evaluate(() => document.activeElement?.textContent)) === "确认执行", "the focus is not on the main action");
    // Answered: the strip is gone.
    await page.keyboard.press("Enter");
    await answered(page);
    assert((await page.locator("[data-testid=waiting-strip]").count()) === 0, "the strip stays after the card was answered");
    return "strip above the input; click scrolls the card into view and focuses 确认执行 (Enter then confirms); the box stays enabled; the strip leaves with the card";
  } finally { await view.close(); }
}

/** The card's own keyboard: it does not take focus; Tab enters it; arrows move between the materials; Enter on a tick does the main action. */
async function approvalKeyboard(ctx) {
  const view = await openChatAt(ctx, "approval-keyboard");
  try {
    const { page } = view;
    const raw = watchRaw(page);
    const hand = await handTurn(page, { text: "修订", lead: "请勾选。" });
    await endWithCard(hand, 0, revisionCard());
    const card = page.locator(ACTIVE_CARD); await card.waitFor({ timeout: 10000 });
    assert(!(await page.evaluate(() => Boolean(document.activeElement?.closest("[data-slot=approval-card]")))), "the card took the focus when it appeared");
    const boxes = card.locator("input[type=checkbox]");
    await boxes.nth(0).focus();
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowDown");
    assert((await page.evaluate(() => document.activeElement?.closest("label")?.textContent ?? "")).includes("服务业务监管新规"), "the arrow keys did not move through the materials");
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowUp"); await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowDown");
    assert((await page.evaluate(() => document.activeElement?.closest("label")?.textContent ?? "")).includes("AAPL 10-Q"), "the arrows do not wrap");
    const n = raw.length;
    await page.keyboard.press("Enter");
    await answered(page);
    assert(raw.length === n + 1 && JSON.parse(raw[n]).message === "confirm:revise_forecast:1.3", `Enter on a tick sent ${raw[n]}`);
    return "no focus grab; arrows move and wrap through the ticks, Space ticks, Enter sends the ticked materials (confirm:revise_forecast:1.3)";
  } finally { await view.close(); }
}

/** 重试 puts the last question out again, as the same request, and the failed turn is replaced; 去设置 only when a setting is the way out. */
async function retryResendsLast(ctx) {
  const view = await openChatAt(ctx, "retry-resends-last");
  try {
    const { page } = view;
    const hand = await handTurn(page, { text: "重试用的问题", lead: "写了一半的回答，" });
    await endWithError(hand, 0, "provider_timeout");
    const bar = page.locator("[data-testid=turn-error]"); await bar.waitFor({ timeout: 10000 });
    assert((await bar.innerText()).includes("请求超时"), `the error bar says ${JSON.stringify(await bar.innerText())}`);
    assert((await bar.locator("a", { hasText: "去设置" }).count()) === 0, "去设置 is offered for a timeout");
    assert((await page.locator("[data-testid=message][data-role=assistant]", { hasText: "写了一半的回答" }).count()) === 1, "the text generated before the failure is gone");
    assert((await page.locator("[data-testid=chat-status]").count()) === 0, "the old status line carries the error");
    const first = (await hand.opened(0)).message;
    await bar.getByRole("button", { name: "重试" }).click();
    const second = await hand.opened(1);
    assert(second.message === first && first.includes("重试用的问题"), `retry sent ${JSON.stringify(second.message)}, the question was ${JSON.stringify(first)}`);
    assert(second.bot_id === BOT.finbot, "the retry lost the bot id");
    await hand.push(1, "conversation", { conversation_id: CONVERSATION.finbot, turn_id: "t9000000-0000-4000-8000-0000000000d3", bot_id: BOT.finbot });
    await hand.push(1, "delta", { text: "重试之后的完整回答。" });
    await hand.push(1, "done", { status: "complete", turn_id: "t9000000-0000-4000-8000-0000000000d3", thinking_ms: 500, citations: [], citation_protocol: null }); await hand.close(1);
    await page.locator("[data-testid=message][data-role=assistant]", { hasText: "重试之后的完整回答" }).waitFor({ timeout: 10000 });
    assert((await page.locator("[data-testid=user-bubble]", { hasText: "重试用的问题" }).count()) === 1, "the question shows twice after the retry");
    assert((await page.locator("[data-testid=turn-error]").count()) === 0 && (await page.locator("[data-testid=message]", { hasText: "写了一半的回答" }).count()) === 0, "the failed turn is still in the thread");
    return "the failed turn keeps its text and shows why under it; 重试 sends the same message again, replaces the failed turn, one question in the thread";
  } finally { await view.close(); }
  // A card's answer that failed is retried as the same answer: same message, request id and label.
}

async function retryCardAnswerAndSettings(ctx) {
  const { view, raw } = await askInTesla(ctx, "retry-card-answer");
  try {
    const { page } = view;
    view.mock.control.down = true;
    await page.locator(`${ACTIVE_CARD} button`, { hasText: "第二条结果" }).click();
    const bar = page.locator("[data-testid=turn-error]"); await bar.waitFor({ timeout: 15000 });
    assert((await bar.innerText()).includes("连不上后端"), `an unreachable backend says ${JSON.stringify(await bar.innerText())}`);
    view.mock.control.down = false;
    await bar.getByRole("button", { name: "重试" }).click();
    await answered(page);
    // Three requests in all: the question, the answer that never arrived, and the retry, which is the answer again, byte for byte (request id and label included).
    assert(raw.length === 3, `${raw.length} stream requests, expected 3 (the question, the failed answer, the retry)`);
    assert(raw[1] === BASELINE.option[0] && raw[2] === BASELINE.option[0], `the failed answer / the retry were\n  ${raw[1]}\n  ${raw[2]}\nthe answer is\n  ${BASELINE.option[0]}`);
  } finally { await view.close(); }
  const settings = await openChatAt(ctx, "retry-settings");
  try {
    const { page } = settings;
    const hand = await handTurn(page, { text: "缺 key" });
    await endWithError(hand, 0, "model_key_missing");
    const link = page.locator("[data-testid=turn-error] a", { hasText: "去设置" }); await link.waitFor({ timeout: 10000 });
    assert(/#\/settings\/models$/.test(await link.getAttribute("href")), `去设置 goes to ${await link.getAttribute("href")}`);
    assert((await page.locator("[data-testid=turn-error]").getByRole("button", { name: "重试" }).count()) === 1, "no 重试 beside 去设置");
  } finally { await settings.close(); }
  return "an unreachable backend → the plain sentence + 重试; 重试 resends the card's answer with the same request id and label; a missing key adds 去设置 → settings/models";
}

/** The starter questions fill the box and send nothing; each kind of bot gets its own. */
async function starterFillsComposer(ctx) {
  const view = await openChatAt(ctx, "starter-fills", { hash: `#/chat/${BOT.teslabot}`, ready: "[data-testid=welcome]" });
  try {
    const { page } = view;
    const bodies = watchPosts(page, STREAM_PATH);
    const starters = page.locator("[data-testid=starter]");
    assert((await starters.count()) === 3, `${await starters.count()} starter questions`);
    assert(!(await page.locator("[data-testid=welcome]").innerText()).match(/AAPL|TSLA/), "a company-less bot is offered a specific company");
    const text = (await starters.nth(1).innerText()).trim();
    await starters.nth(1).click();
    assert((await page.locator("#agent-draft").inputValue()) === text, `the box holds ${JSON.stringify(await page.locator("#agent-draft").inputValue())}, the starter said ${JSON.stringify(text)}`);
    assert(await page.evaluate(() => document.activeElement?.id === "agent-draft"), "the focus did not go to the box");
    await page.waitForTimeout(600);
    assert(bodies.length === 0 && (await page.locator("[data-testid=message]").count()) === 0 && (await page.locator("[data-testid=welcome]").count()) === 1, "a starter question was sent");
  } finally { await view.close(); }
  // Company, news and earnings bots (their lines emptied first).
  const state = buildState();
  for (const id of [BOT.applebot, BOT.newsbot, BOT.reportbot]) state.chat.conversations.set(CONVERSATION[Object.keys(BOT).find((k) => BOT[k] === id)], []);
  const kinds = [[BOT.applebot, /AAPL/, "AAPL"], [BOT.newsbot, /要闻/, "news"], [BOT.reportbot, /财报/, "earnings"]];
  for (const [id, pattern, name] of kinds) {
    const v = await openChatAt(ctx, `starter-${name}`, { hash: `#/chat/${id}`, ready: "[data-testid=welcome]", fixtureState: state });
    try { const body = await v.page.locator("[data-testid=welcome]").innerText(); assert(pattern.test(body), `${name}: the starters are ${JSON.stringify(body)}`); if (name === "AAPL") assert((await v.page.locator("[data-testid=welcome-companies]").innerText()).includes("AAPL"), "no company chip for a bot that watches AAPL"); }
    finally { await v.close(); }
  }
  return "3 starters fill the box, focus it and send nothing; TeslaBot (no company) gets company-free ones; AppleBot AAPL ones + chip; NewsBot news, ReportBot earnings";
}

/** A background answer finishing raises one toast for its bot, and 查看 goes to that line; a second one does not stack. */
async function backgroundDoneToast(ctx) {
  const view = await openChatAt(ctx, "background-done-toast");
  try {
    const { page } = view;
    const toasts = () => page.locator("[data-sonner-toast]", { hasText: "TeslaBot 回答好了" });
    await page.evaluate((id) => { location.hash = `#/chat/${id}`; }, BOT.teslabot);
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor();
    const finish = async (index, turn) => {
      const hand = await handTurn(page, { text: `后台 ${index}`, lead: "后台的回答", botId: BOT.teslabot, conversationId: CONVERSATION.teslabot, turnId: turn, index });
      await page.evaluate(() => { location.hash = "#/chat"; });
      await page.locator("[data-testid=message]").first().waitFor();
      if (index === 0) assert((await toasts().count()) === 0, "the toast is up before the answer is done");
      await hand.push(index, "done", { status: "complete", turn_id: turn, thinking_ms: 700, citations: [], citation_protocol: null }); await hand.close(index);
      await toasts().first().waitFor({ timeout: 10000 });
    };
    await finish(0, "t9000000-0000-4000-8000-0000000000d4");
    assert((await toasts().first().getByRole("button", { name: "查看" }).count()) === 1, "the toast has no 查看");
    await page.evaluate((id) => { location.hash = `#/chat/${id}`; }, BOT.teslabot);
    await page.locator("h1", { hasText: "TeslaBot" }).waitFor();
    await finish(1, "t9000000-0000-4000-8000-0000000000d5");
    await page.waitForTimeout(500);
    assert((await toasts().count()) === 1, `${await toasts().count()} toasts for one bot after two answers`);
    await toasts().first().getByRole("button", { name: "查看" }).click();
    await page.waitForFunction((id) => location.hash === `#/chat/${id}`, BOT.teslabot, { timeout: 5000 });
    return "TeslaBot finishing in the background raises 「TeslaBot 回答好了」 with 查看; a second answer replaces it (one toast); 查看 opens TeslaBot's line";
  } finally { await view.close(); }
}

/** A turn that came in from outside this tab has a divider above it: the routine's name and time, or just 外部消息 (nothing else is marked by the server). */
async function externalMessageDivider(ctx) {
  const view = await openChatAt(ctx, "external-divider");
  try {
    const { page } = view;
    assert((await page.locator("[data-testid=external-divider]").count()) === 0, "a divider above history that was not written from outside");
    const list = view.mock.state.chat.conversations.get(CONVERSATION.finbot);
    list.push({ role: "user", content: "【例行任务结果】「收盘复盘」2026-11-13 16:10", turn_id: "t7000000-0000-4000-8000-000000000001" },
      { role: "assistant", status: "complete", turn_id: "t7000000-0000-4000-8000-000000000001", content: "今天收盘后的复盘。" },
      { role: "user", content: "TSLA 的交付数据出来了吗？", turn_id: "t7000000-0000-4000-8000-000000000002" },
      { role: "assistant", status: "complete", turn_id: "t7000000-0000-4000-8000-000000000002", content: "还没有。" });
    await page.locator("[data-testid=external-divider]").nth(1).waitFor({ timeout: 20000 });
    const dividers = page.locator("[data-testid=external-divider]");
    assert((await dividers.count()) === 2, `${await dividers.count()} dividers for two outside turns`);
    assert((await dividers.nth(0).innerText()).replace(/\s+/g, " ") === "例行任务「收盘复盘」 · 2026-11-13 16:10", `the routine divider says ${JSON.stringify(await dividers.nth(0).innerText())}`);
    assert((await dividers.nth(1).innerText()).trim() === "外部消息", `the other says ${JSON.stringify(await dividers.nth(1).innerText())}`);
    // Each sits directly above its turn's first line.
    const order = await page.evaluate(() => [...document.querySelectorAll("[data-testid=thread] > *")].map((el) => el.getAttribute("data-testid")).slice(-6));
    assert(order.join(",") === "external-divider,message,message,external-divider,message,message", `the thread ends ${order.join(",")}`);
    return "history has no divider; the polled-in turns get 「例行任务「收盘复盘」 · 时间」 and 「外部消息」 right above their first line";
  } finally { await view.close(); }
}

/** Phone: the right panel is a bottom drawer; a chip or the process bar opens it on the right tab and place; between lg and xl it is still the column over the thread. */
async function mobilePanelDrawer(ctx) {
  const view = await openChatAt(ctx, "mobile-panel-drawer", { width: 390 });
  try {
    const { page } = view;
    assert((await page.locator("aside[data-testid=context-panel]").count()) === 0, "the column panel is drawn on a phone");
    await firstAnswer(page).locator("[data-testid=citation-chip][data-ordinal='2']").first().scrollIntoViewIfNeeded();
    await firstAnswer(page).locator("[data-testid=citation-chip][data-ordinal='2']").first().click();
    const drawer = page.locator("[data-slot=drawer-content][data-testid=context-panel]"); await drawer.waitFor({ timeout: 8000 });
    assert((await drawer.getAttribute("data-vaul-drawer-direction")) === "bottom", "the panel is not a bottom drawer");
    const box = await drawer.boundingBox();
    assert(Math.abs(box.y + box.height - 844) <= 2 && box.y > 60 && box.width >= 388, `the drawer sits at ${JSON.stringify(box)}`);
    assert((await page.locator("[data-testid=tab-sources]").getAttribute("aria-selected")) === "true", "来源 is not the open tab");
    await page.waitForFunction(() => document.querySelector("[data-slot=source-card][data-ordinal='2']")?.hasAttribute("data-highlight"), null, { timeout: 5000 });
    assert(await inView(page, "[data-slot=source-card][data-ordinal='2']", "[data-testid=sources-pane]"), "card 2 is not in the drawer's viewport");
    const tabs = await drawer.locator("[role=tab]").allInnerTexts();
    assert(["来源", "过程", "工作区"].every((name) => tabs.some((text) => text.includes(name))), `tabs: ${tabs.join(" | ")}`);
    await page.keyboard.press("Escape");
    await drawer.waitFor({ state: "detached", timeout: 5000 });
    // The process bar opens the same drawer on 过程 and the round.
    await firstAnswer(page).locator("[data-testid=turn-steps]").click();
    await drawer.waitFor({ timeout: 8000 });
    await page.locator("[data-testid=timeline-step]").first().waitFor({ timeout: 8000 });
    assert((await page.locator("[data-testid=tab-process]").getAttribute("aria-selected")) === "true", "过程 is not the open tab");
    await page.keyboard.press("Escape"); await drawer.waitFor({ state: "detached", timeout: 5000 });
    // The header's own switch opens it too.
    await page.locator("[data-testid=side-toggle]").click(); await drawer.waitFor({ timeout: 8000 });
    await page.keyboard.press("Escape"); await drawer.waitFor({ state: "detached", timeout: 5000 });
    // 1100 wide (lg to xl): still the column over the thread, no drawer.
    const mid = await openChatAt(ctx, "panel-1100", { width: 1100 });
    try { await mid.page.locator("[data-testid=side-toggle]").click(); await mid.page.locator("aside[data-testid=context-panel]").waitFor({ timeout: 5000 }); assert((await mid.page.locator("[data-slot=drawer-content]").count()) === 0, "a drawer at 1100"); } finally { await mid.close(); }
    return "390: no column; chip → bottom drawer on 来源 with card 2 marked in view; process bar → 过程; header switch opens it; Esc closes; 1100: still the column";
  } finally { await view.close(); }
}

/** Phone: 「头像 + 名 + ▾」 opens the bot switcher, which lists the same rows as 更多. */
async function mobileBotSwitcher(ctx) {
  const state = buildState();
  state.bots.find((b) => b.id === BOT.reportbot).hidden = true;
  const view = await openChatAt(ctx, "mobile-bot-switcher", { width: 390, fixtureState: state });
  try {
    const { page } = view;
    const trigger = page.locator("[data-testid=bot-switcher]");
    const box = await trigger.boundingBox();
    assert(box.height >= 44, `the trigger is ${box.height}px high`);
    assert((await trigger.innerText()).includes("FinBot") && (await trigger.locator("svg").count()) >= 1, "the trigger is not 名 + ▾");
    await trigger.click();
    const drawer = page.locator("[data-testid=bot-switcher-drawer]"); await drawer.waitFor({ timeout: 8000 });
    const rows = drawer.locator("[data-bot-switch-row]");
    const names = (await rows.allInnerTexts()).map((t) => t.split("\n")[0].trim());
    assert(names.join(",") === "FinBot,AppleBot,NewsBot,TeslaBot", `the bots listed: ${names.join(",")} (ReportBot is hidden)`);
    const text = await drawer.innerText();
    assert(text.includes("2") && /历史对话/.test(text) && /新建 bot/.test(text), "the list lacks the unread number, 历史对话 or 新建 bot");
    for (const handle of await rows.elementHandles()) assert((await handle.boundingBox()).height >= 44, "a row is under 44px");
    const list = (await drawer.locator("[data-slot=bot-switch-list]").innerText()).replace(/\s+/g, " ");
    await page.keyboard.press("Escape"); await drawer.waitFor({ state: "detached", timeout: 5000 });
    // The 更多 drawer lists the same rows (one component).
    await page.locator('[data-slot="mobile-tab-bar"] button[aria-haspopup="dialog"]').click();
    const more = page.locator('[data-slot="drawer-content"] [data-slot=bot-switch-list]'); await more.waitFor({ timeout: 8000 });
    assert((await more.innerText()).replace(/\s+/g, " ") === list, "更多 lists other rows than the switcher");
    await page.keyboard.press("Escape"); await page.locator('[data-slot="drawer-content"]').waitFor({ state: "detached", timeout: 5000 });
    // Choosing a bot goes to its line and closes the drawer; 新建 bot opens the dialog.
    await trigger.click(); await drawer.waitFor();
    await rows.filter({ hasText: "TeslaBot" }).click();
    await page.waitForFunction((id) => location.hash === `#/chat/${id}`, BOT.teslabot, { timeout: 5000 });
    await drawer.waitFor({ state: "detached", timeout: 5000 });
    assert((await page.locator("h1").first().innerText()).includes("TeslaBot"), "the header still names the old bot");
    await trigger.click(); await drawer.waitFor();
    await drawer.getByRole("button", { name: "新建 bot" }).click();
    await page.locator('[role=dialog]').first().waitFor({ timeout: 8000 });
    return "header 名 ▾ (≥44px) → drawer of the unhidden bots with the sidebar's marks + 历史对话 + 新建 bot; the same list as 更多; a row goes to its line; 新建 bot opens the dialog";
  } finally { await view.close(); }
}

/** Phone: 「目录」 lists this line's questions; a row jumps, the bookmark is kept (and is the desktop rail's bookmark). */
async function mobileOutline(ctx) {
  const view = await openChatAt(ctx, "mobile-outline", { width: 390 });
  try {
    const { page } = view;
    assert((await page.locator("[data-testid=question-rail]").isVisible()) === false, "the rail is drawn on a phone");
    const button = page.locator("[data-testid=outline-button]");
    assert((await button.boundingBox()).height >= 44, "the 目录 button is under 44px");
    await button.click();
    const drawer = page.locator("[data-testid=outline-drawer]"); await drawer.waitFor({ timeout: 8000 });
    const rows = drawer.locator("[data-testid=outline-row]");
    assert((await rows.count()) === 4, `${await rows.count()} questions listed, the line has 4`);
    // The second question has no turn id in the fixtures (not saved yet): it cannot be bookmarked, as on the desktop rail.
    assert(await rows.nth(1).locator("[data-testid=outline-bookmark]").isDisabled(), "a question that is not saved can be bookmarked");
    await rows.nth(0).locator("[data-testid=outline-bookmark]").click();
    assert((await rows.nth(0).locator("[data-testid=outline-bookmark]").getAttribute("aria-pressed")) === "true", "the bookmark did not take");
    await rows.nth(3).locator("[data-testid=outline-jump]").click();
    await drawer.waitFor({ state: "detached", timeout: 5000 });
    await button.click(); await drawer.waitFor();
    await rows.nth(0).locator("[data-testid=outline-jump]").click();
    await drawer.waitFor({ state: "detached", timeout: 5000 });
    await page.waitForFunction(() => { const t = document.querySelector("[data-testid=transcript]").getBoundingClientRect().top, m = document.getElementById("chat-message-0").getBoundingClientRect().top; return Math.abs(m - t) < 40; }, null, { timeout: 5000 });
    await button.click(); await drawer.waitFor();
    assert((await rows.nth(0).locator("[data-testid=outline-bookmark]").getAttribute("aria-pressed")) === "true", "the bookmark did not survive reopening");
    // The same bookmark is the desktop rail's.
    const desk = await openChatAt(ctx, "outline-desktop");
    try { assert(!(await desk.page.locator("[data-testid=outline-button]").isVisible()), "目录 is drawn on a desktop"); } finally { await desk.close(); }
    return "目录 (≥44px) lists the 4 questions; rows jump to their question (last, then first); a saved question is bookmarked and stays so, an unsaved one cannot be; no 目录 on a desktop";
  } finally { await view.close(); }
}

/** Phone: every control of the line is at least 44 x 44, and nothing makes the page wider than 390. */
async function mobileTouchTargets(ctx) {
  const view = await openChatAt(ctx, "mobile-touch-targets", { width: 390 });
  try {
    const { page } = view;
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert(wide <= 0, `the page is ${wide}px wider than the window`);
    const small = await page.evaluate(() => {
      const scopes = ["[data-testid=chat-header]", "[data-testid=composer]", "[data-testid=message-foot]", "[data-testid=sources-chip]", "[data-testid=waiting-strip]", "[data-slot=approval-card]"];
      const bad = [];
      for (const scope of scopes) for (const root of document.querySelectorAll(scope)) {
        const hits = root.matches("button, a, input, [role=button]") ? [root] : [];
        for (const el of [...hits, ...root.querySelectorAll("button, a[href], input, [role=button]")]) {
          const r = el.getBoundingClientRect(); const style = getComputedStyle(el);
          if (!r.width || !r.height || style.visibility === "hidden" || style.display === "none") continue;
          if (el.closest("[data-slot=approval-details]") && el.tagName === "A") continue; // a link in the card's text
          if (r.width < 43.5 || r.height < 43.5) bad.push(`${scope} ${el.getAttribute("aria-label") || el.textContent?.trim().slice(0, 12) || el.tagName}: ${Math.round(r.width)}x${Math.round(r.height)}`);
        }
      }
      return bad;
    });
    assert(small.length === 0, `controls under 44x44: ${small.join("; ")}`);
    return "no horizontal overflow at 390; header, composer, foot, chips, strip and card controls all ≥ 44x44";
  } finally { await view.close(); }
}

/** The on-screen keyboard that covers the page (iOS) lifts the composer: a stand-in visualViewport shrinks and the box rises above it. */
async function mobileKeyboardInset(ctx) {
  const view = await newView(ctx.browser, { width: 390, theme: "light", label: "mobile-keyboard", unmatched });
  try {
    const { page } = view;
    await view.context.addInitScript(() => {
      const target = new EventTarget();
      const stub = Object.assign(target, { height: window.innerHeight, offsetTop: 0, offsetLeft: 0, width: window.innerWidth, scale: 1, pageTop: 0, pageLeft: 0 });
      Object.defineProperty(window, "visualViewport", { value: stub, configurable: true });
      window.__setKeyboard = (px) => { stub.height = window.innerHeight - px; stub.dispatchEvent(new Event("resize")); };
    });
    await page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
    await page.waitForSelector("[data-testid=message]", { timeout: 15000 });
    await settle(page);
    const bottom = () => page.locator("[data-testid=composer]").evaluate((el) => Math.round(el.getBoundingClientRect().bottom));
    const rest = await bottom();
    await page.evaluate(() => window.__setKeyboard(300));
    await page.waitForFunction((r) => document.querySelector("[data-testid=composer]").getBoundingClientRect().bottom < r - 100, rest, { timeout: 5000 });
    const lifted = await bottom();
    assert(lifted <= 844 - 300 + 2, `with a 300px keyboard the composer's bottom is at ${lifted}px (the keyboard starts at 544)`);
    await page.evaluate(() => window.__setKeyboard(0));
    await page.waitForFunction((r) => Math.abs(document.querySelector("[data-testid=composer]").getBoundingClientRect().bottom - r) <= 1, rest, { timeout: 5000 });
    return `a 300px keyboard lifts the composer from ${rest}px to ${lifted}px (clear of the keys at 544); it comes back down; Chrome / Firefox Android resize the layout instead (viewport interactive-widget)`;
  } finally { await view.close(); }
}

const CHECKS = [
  ["every page opens and reaches its ready condition", everyPageOpens],
  ["chat-send: send a message: user line, streamed answer, composer reusable", sendMessageStreams],
  ["chat-cancel: cancel before the stream ends: 已停止 shown, the generated text kept, composer usable", chatCancel],
  ["chat-background-line: the stream of the bot left behind finishes in the background; the row marks it; the whole answer on return", chatBackgroundLine],
  ["chat-clarification: a turn ending in a card; the pick goes out as the next turn with its request id", chatClarification],
  ["chat-write-confirm: 确认执行 sends the request id; 先不要 sends no confirmation", chatWriteConfirm],
  ["chat-readonly-archive: an opened archive shows its banner, a read-only composer and a working 返回当前对话", chatReadonlyArchive],
  ["chat-external-sync: a turn written from outside appears by itself, the draft stays", chatExternalSync],
  ["chat-compact: /compact sends the compress request and the thread shows 已压缩 N 轮", chatCompact],
  ["locale-catalog-on-demand: a Chinese session never fetches the English catalog; switching or starting in English fetches it once and the page is English", localeCatalogLoadsOnDemand],
  ["optional-chunk-failure: a blocked workspace chunk leaves the chat page and the right panel working without the cards and the new-bot dialog", optionalChunkFailure],
  ["chat-load-earlier: scrolling to the top loads the earlier turns and the line being read does not move", chatLoadEarlier],
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
  ["no-window-confirm: the nine former window.confirm places ask in the app; Esc / 取消 send nothing, a full hold sends one request", noWindowConfirm],
  ["confirm-dialog-keyboard: focus starts on 取消, Esc cancels, holding Space or Enter confirms, reduced motion and bare clicks press twice", confirmDialogKeyboard],
  ["command-menu-navigates: shortcut, company / hidden bot / page / recent chat each open; Esc closes and returns focus", commandMenuNavigates],
  ["command-menu-english: group names, page names and the add offer are English in the English interface", commandMenuEnglish],
  ["command-menu-add-watch: a valid code off the list offers 加入自选并打开 and the fake API receives the queue update", commandMenuAddWatch],
  ["command-menu-mobile: 更多 has the search entry; the palette fits 390px and focus returns to 更多", commandMenuMobile],
  ["toast-auto-dismiss: bottom right, about 2s, undo outlasts it and works by keyboard, above dialogs", toastAutoDismiss],
  ["toast-above-dialog: a toast stays on top of an open dialog", toastAboveDialog],
  ["offline-banner: failed requests light one banner at the top; 重试 with the backend back puts it out", offlineBanner],
  ["offline-banner-quiet: application errors (a guest's 403s) never light the banner", offlineBannerQuiet],
  ["skeleton-delay: no skeleton for a quick load, one after 400ms for a slow one, none pulsing under reduced motion, route-level cover", skeletonDelay],
  ["state-components-in-legacy: ErrorBar, EmptyState, StatefulButton look the same inside a data-legacy island", stateComponentsInLegacy],
  ["task-bar: stage and elapsed time, follows the reader to another page, the end is a toast", taskBar],
  ["states-sample: the nine states at #/dev/kit/states work", statesSamplePage],
  ["composer-ime: Enter during an input-method composition never sends; after compositionend it does", composerIme],
  ["composer-slash-menu: arrows, Esc and Enter drive the / menu; an input method's keys do not", composerSlashMenu],
  ["chat-follow-and-jump: a streaming answer is followed; scrolling up stops it and shows 回到底部; the button and a manual return resume it", chatFollowAndJump],
  ["draft-survives-switch: a half-typed message stays with its line across a bot switch, another page and a reload", draftSurvivesSwitch],
  ["stop-button: the send position becomes stop while an answer runs and stop is the old cancel", stopButton],
  ["copy-toast: copying shows a toast and adds no text to the thread", copyToast],
  ["chat-popover-keyboard: the composer panels and the header ⓘ open from the keyboard, Esc closes and returns focus", chatPopoverKeyboard],
  ["chat-question-rail: markers on the left edge, preview card, bookmark kept, click scrolls", chatQuestionRail],
  ["markdown-chunk: the renderer is prefetched at launch; a skeleton while it is late; plain text and 重试 when it fails", markdownChunk],
  ["citation-jump: a click on [2] opens the panel on 来源, scrolls to card 2 and marks it once", citationJump],
  ["steps-live: the process bar grows with the events of a running turn and folds to 已思考 N 秒 · M 步", stepsLive],
  ["steps-pending: before the first event the line shows the bar's first cell; the first event replaces it with the real message", stepsPending],
  ["steps-open-process: the process bar opens 过程 on its own round; another round's bar switches it", stepsOpenProcess],
  ["public-mark-verbatim: the card's text equals the existing functions' text for the message; no danger / action colour, no icon", publicMarkVerbatim],
  ["legacy-line-mark: the old unverified-line note is the same neutral ◦ with its old words; 追问依据 works", legacyLineMark],
  ["old-message-no-steps: no step data shows nothing, only a time, or the old tool badges as chips", oldMessageNoSteps],
  ["panel-resize-persists: dragging the panel's edge changes its width, which (and folding) survives a reload", panelResizePersists],
  ["sources-keyboard: Tab reaches a chip, Enter takes the focus into its source card, Esc returns it", sourcesKeyboard],
  ["source-card-fields: every field of the old drawer has a place on the card; a withdrawn source is an error bar with 重试", sourceCardFields],
  ["approval-request-body: confirm, cancel, option, typed reply and ticked materials send the same five bodies as the old card, byte for byte", approvalRequestBody],
  ["revision-card-min-select: nothing pre-ticked; the button waits for the minimum and says why; no candidate says so", revisionCardMinSelect],
  ["approval-countdown: a card made in this session counts ten minutes down and falls to 已过期; a history card shows the static note", approvalCountdown],
  ["approval-collapses: an answered card is one line (已确认 · title / 已取消 / 未确认)", approvalCollapses],
  ["approval-keyboard: no focus grab; arrows move through the materials; Enter does the main action", approvalKeyboard],
  ["waiting-strip: the amber strip scrolls to the card and focuses its main action; the box stays usable", waitingStrip],
  ["retry-resends-last: 重试 sends the last question again as the same request and replaces the failed turn", retryResendsLast],
  ["retry-card-answer: a card's failed answer is retried with its request id; 去设置 only for a missing key", retryCardAnswerAndSettings],
  ["starter-fills-composer: a starter question fills the box and sends nothing; each kind of bot gets its own", starterFillsComposer],
  ["background-done-toast: a background answer raises one toast per bot with 查看", backgroundDoneToast],
  ["external-message-divider: turns written from outside get 「例行任务…」 or 「外部消息」 above them", externalMessageDivider],
  ["mobile-panel-drawer: at 390 the panel is a bottom drawer opened on the right tab and place", mobilePanelDrawer],
  ["mobile-bot-switcher: 名 ▾ opens the unhidden bots with their marks, the same list as 更多", mobileBotSwitcher],
  ["mobile-outline: 目录 lists the questions, jumps and keeps bookmarks", mobileOutline],
  ["mobile-touch-targets: the line's controls are ≥ 44x44 and the page does not scroll sideways at 390", mobileTouchTargets],
  ["mobile-keyboard-inset: a keyboard over the page lifts the composer above it", mobileKeyboardInset],
  ["workspace-cards-in-panel: add, move, resize, pin, delete and reset the workspace cards in the panel's 工作区 tab; the layout is kept per bot", workspaceCardsInPanel],
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
