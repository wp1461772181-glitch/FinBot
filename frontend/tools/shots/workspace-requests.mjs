// P9.1: the reads the chat page's 工作区 cards send, as a record.  Used twice: by the one-off recorder (run on the OLD markup, written to
// fixtures/workspace-requests-baseline.json) and by the smoke check `workspace-cards-requests` (run on whatever is built now, compared with that file).
// The drive uses only what is true of both markups: the pane's testid, `section[aria-label]` cards, and roles + accessible names for the controls,
// so it does not depend on the cards' class names or on whether a menu is a native <select> or a Radix Select.
import { newView, settle } from "./harness.mjs";
import { BOT } from "./fixtures/ids.mjs";

const API = "https://api.example.test";
export const LAYOUT_KEY = `market-evidence-agent:workspace:${BOT.finbot}:v1`;
export const ALL_CARDS = ["price", "forecast", "materials", "filings", "routines", "brief", "watchlist", "portfolio"];

/** Open FinBot's line at 1440 with `layout` stored for it (only when the browser holds none yet, so a reload keeps what the page wrote). */
export async function openWithLayout(ctx, label, layout, { unmatched }) {
  const view = await newView(ctx.browser, { width: 1440, theme: "light", label, unmatched });
  const sent = [];
  view.page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.origin !== API || r.method() === "OPTIONS") return;
    sent.push(`${r.method()} ${u.pathname}${u.search}`);
  });
  if (layout) await view.context.addInitScript(([key, value]) => { if (!localStorage.getItem(key)) localStorage.setItem(key, value); }, [LAYOUT_KEY, JSON.stringify(layout)]);
  await view.page.goto(`${ctx.server.url}#/chat`, { waitUntil: "load" });
  await view.page.waitForSelector("[data-testid=message]", { state: "visible", timeout: 30000 });
  await paneQuiet(view.page, layout ? layout.length : null);
  return { ...view, sent };
}

/** The pane is there, every card it holds has stopped reading, and the network is idle. */
export async function paneQuiet(page, expectCards = null) {
  await page.waitForFunction((expect) => {
    const pane = document.querySelector("[data-testid=workspace-pane]");
    if (!pane) return false;
    const cards = pane.querySelectorAll("section[aria-label]").length;
    if (expect !== null && cards !== expect) return false;
    return !/正在读取/.test(pane.innerText);
  }, expectCards, { timeout: 30000 });
  await settle(page, { pinTranscript: false });
}

/** Pick a value in a menu that is a native <select> or a Radix Select (both are role=combobox). */
export async function choose(page, combo, value) {
  const tag = await combo.evaluate((el) => el.tagName);
  if (tag === "SELECT") await combo.selectOption(value);
  else { await combo.click(); await page.getByRole("option", { name: value, exact: true }).click(); }
}

const multiset = (lines) => { const m = new Map(); for (const l of lines) m.set(l, (m.get(l) ?? 0) + 1); return m; };
/** `after` minus `before`, as a sorted list (duplicates kept: a card that reads twice shows twice). */
function minus(after, before) {
  const left = multiset(before), out = [];
  for (const l of after) { const n = left.get(l) ?? 0; if (n > 0) left.set(l, n - 1); else out.push(l); }
  return out.sort();
}

/**
 * Drive the cards and return { cards: {id: [lines]}, actions: {name: [lines]}, writes: [lines] }.
 *   cards   each card alone in the pane, minus what the page sends with an empty pane (the page's own reads)
 *   actions the reads that are NEW after an action, with all eight cards in the pane
 *   writes  every non-GET the whole run sent, bar the shell's own 「mark read」 (there should be none)
 */
export async function collectWorkspaceRequests(ctx, { unmatched }) {
  const result = { cards: {}, actions: {}, writes: [] };
  // The page marks the open bot's line read once per load (POST …/bots/<id>/read, the shell's own call); that is not a card's, so it is left out.
  const writes = (sent) => sent.filter((l) => !l.startsWith("GET ") && !/^POST \/agent-chat\/bots\/[^/]+\/read$/.test(l));
  const baseView = await openWithLayout(ctx, "ws-req-empty", [], { unmatched });
  const empty = baseView.sent.slice(); result.writes.push(...writes(empty)); await baseView.close();
  for (const id of ALL_CARDS) {
    const view = await openWithLayout(ctx, `ws-req-${id}`, [{ card: id }], { unmatched });
    result.cards[id] = minus(view.sent, empty); result.writes.push(...writes(view.sent)); await view.close();
  }
  const all = ALL_CARDS.map((card) => ({ card }));
  const pane = (view) => view.page.locator("[data-testid=workspace-pane]");
  const act = async (name, drive) => {
    const view = await openWithLayout(ctx, `ws-req-${name}`, all, { unmatched });
    try {
      const mark = view.sent.length;
      await drive(view);
      await paneQuiet(view.page, all.length);
      result.actions[name] = view.sent.slice(mark).sort(); result.writes.push(...writes(view.sent));
    } finally { await view.close(); }
  };
  await act("switch-current-stock", async (view) => { await choose(view.page, pane(view).getByRole("combobox", { name: "当前股票" }), "MSFT"); });
  await act("pin-price-card", async (view) => {
    const p = pane(view);
    await p.getByRole("button", { name: /编辑卡片/ }).click();
    const pin = p.getByRole("textbox", { name: "固定股票" }).first();
    await pin.fill("NVDA"); await pin.blur();
    await p.getByRole("button", { name: "完成" }).click();
  });
  await act("pick-from-watchlist-card", async (view) => {
    await pane(view).locator("section[aria-label=自选列表]").getByRole("button", { name: "TSLA", exact: true }).click();
  });
  result.writes.sort();
  return result;
}

/** What differs between a record and the baseline, as sentences (empty = identical). */
export function diffRecords(now, base) {
  const problems = [];
  const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
  const compare = (kind, name, a, b) => {
    if (b === undefined) { problems.push(`${kind} ${name}: not in the baseline`); return; }
    if (same(a, b)) return;
    const extra = minus(a, b), missing = minus(b, a);
    problems.push(`${kind} ${name}: ${extra.length ? `${extra.length} extra [${extra.join(" | ")}]` : ""}${extra.length && missing.length ? "; " : ""}${missing.length ? `${missing.length} missing [${missing.join(" | ")}]` : ""}`);
  };
  for (const [k, v] of Object.entries(now.cards)) compare("card", k, v, base.cards[k]);
  for (const [k, v] of Object.entries(now.actions)) compare("action", k, v, base.actions[k]);
  for (const k of Object.keys(base.cards)) if (!(k in now.cards)) problems.push(`card ${k}: not driven now`);
  for (const k of Object.keys(base.actions)) if (!(k in now.actions)) problems.push(`action ${k}: not driven now`);
  compare("writes", "all", now.writes, base.writes);
  return problems;
}
