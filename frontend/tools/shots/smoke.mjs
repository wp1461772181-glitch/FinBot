// Smoke entry: node smoke.mjs --dist <build dir> [--strict]
// One named function per check, registered in CHECKS.  Later phases append checks here.
import { parseArgs } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";
import { summarizeUnmatched } from "./mock-api.mjs";
import { PAGES, waitReady } from "./pages.mjs";
import { BOT } from "./fixtures/ids.mjs";
import { buildState } from "./fixtures/index.mjs";

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

/** Legacy selectors that may match shadcn parts because the match is known to change nothing.  Keep this list short and justified. */
const SELECTOR_MATCH_ALLOWED = new Set([
  "*", // box-sizing: border-box, the same value preflight sets
]);

/** The shadcn parts on #dev-kit must look the same with the whole `legacy` layer deleted from the page. */
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
        await page.goto(`${ctx.server.url}#dev-kit`, { waitUntil: "load" });
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
    await page.goto(`${ctx.server.url}#dev-kit`, { waitUntil: "load" });
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
 * Where the old-browser-default restore applies.  #dev-kit/probe has the same bare tags twice:
 *  - "outside": no data-legacy above them -> plain preflight (margins 0, no list markers, bare button, inherited link colour ...);
 *  - "island": a data-legacy subtree inside a data-slot container (the P2 shell case) -> browser defaults, as the old pages had.
 */
async function legacyScope(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "kit-scope", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#dev-kit/probe`, { waitUntil: "load" });
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
    const open = await page.locator(".bot-rail").first().isVisible().catch(() => false);
    if (!open) await page.locator("button.nav-menu-trigger").click();
    await page.locator(".bot-rail .bot-row").first().waitFor({ state: "visible", timeout: 10000 });
    // The drawer slides in (real motion is on in this view): hover only once the row is on screen.
    await page.waitForFunction(() => { const r = document.querySelector(".bot-rail .bot-row")?.getBoundingClientRect(); return Boolean(r) && r.left >= 0 && r.right <= window.innerWidth; }, null, { timeout: 10000 });
    assert((await page.locator(".bot-rail .bloub-avatar").count()) >= 5, "expected at least 5 bloub avatars in the rail");
    const rafOver = async (ms) => { const before = await page.evaluate(() => window.__rafCalls); await page.waitForTimeout(ms); return (await page.evaluate(() => window.__rafCalls)) - before; };
    const bad = [], seen = {};
    await page.mouse.move(1100, 500);
    await page.waitForTimeout(1000);
    seen.still = await rafOver(3000);
    if (seen.still > 5) bad.push(`still page: ${seen.still} requestAnimationFrame calls in 3 s (limit 5)`);
    const row = page.locator(".bot-rail .bot-row:has(.bloub-avatar)").nth(1); // a bot row (the rail also has plain navigation rows)
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

    // An unread bot (notify) keeps its animation: the unmodified fixture has NewsBot unread.
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
      await unread.page.waitForTimeout(500);
      const before = await unread.page.evaluate(() => window.__rafCalls);
      await unread.page.waitForTimeout(1000);
      seen.notify = (await unread.page.evaluate(() => window.__rafCalls)) - before;
    } finally { await unread.close(); }
    assert(seen.notify >= 20, `an unread bot should keep animating, got ${seen.notify} calls in 1 s`);
    return `still ${seen.still}/3 s, hover ${seen.hover}/1 s, leaving ${seen.release}/0.5 s then settled ${seen.after}/2 s; unread bot ${seen.notify}/1 s`;
  } finally { await view.close(); }
}

/** Colour of an element, as the browser resolves it for `prop`. */
const colorOf = (page, selector, prop = "color") => page.evaluate(([sel, name]) => getComputedStyle(document.querySelector(sel))[name], [selector, prop]);

async function updownSwitchesMarketOnly(ctx) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label: "updown-kit", unmatched });
  try {
    const { page } = view;
    await page.goto(`${ctx.server.url}#dev-kit`, { waitUntil: "load" });
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
    await page.goto(`${ctx.server.url}#admin`, { waitUntil: "load" });
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
export const CHECKS = [
  ["every page opens and reaches its ready condition", everyPageOpens],
  ["send a message: user line, streamed answer, composer reusable", sendMessageStreams],
  ["switch to another bot and back: URL changes, earlier answer kept", switchBotAndBack],
  ["browser back returns to the previous address", backButtonReturns],
  ["theme toggle flips data-theme on <html>", themeToggles],
  ["thinking panel expands to the turn trace", thinkingPanelExpands],
  ["#dev-kit: shadcn parts are identical with the legacy layer removed", kitNotPolluted],
  ["#dev-kit: dialog, menu and select work from the keyboard and return focus", kitKeyboard],
  ["#dev-kit/probe: restore applies only inside data-legacy, preflight everywhere else", legacyScope],
  ["#dev-kit: the up/down switch swaps market colours only (new and old styles); success and error stay", updownSwitchesMarketOnly],
  ["settings page: the up/down choice changes <html data-updown> and survives a reload", updownSettingPersists],
  ["idle-avatars-no-raf: idle sidebar avatars run no frame loop; hover starts it, leaving stops it", idleAvatarsNoRaf],
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
