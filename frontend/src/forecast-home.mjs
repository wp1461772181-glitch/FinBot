// Decisions of the 预测 home page, as pure functions (no React, no window, no network).
//
// Two kinds of record live on the home page and must never look alike (design §2):
//   正式预测 (a formal forecast): three probabilities, scored by Brier and log loss.
//   财报判断 (an earnings judgment): 偏涨 or 偏跌 plus 把握, never a percentage of its own.
// Each has its own view model below.  A judgment model carries no probabilities; a forecast model carries
// no direction word.  Strings that are zh-CN phrase keys are marked `t`; values taken from a record are `v`.

const DAY_MS = 86_400_000;
const EXPIRY_WINDOW_DAYS = 7;
const JUST_EVALUATED_DAYS = 7;

function asDate(value) {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function targetEndMs(row) {
  // The target is a session-close date; counting it as that day's end keeps a row "open" through its last day.
  if (typeof row?.target_end_date !== "string") return null;
  const date = new Date(`${row.target_end_date}T23:59:59Z`);
  return Number.isNaN(date.getTime()) ? null : date.getTime();
}

function decisionMs(row) {
  const date = asDate(row?.decision_at);
  return date ? date.getTime() : 0;
}

/** Tier of one forecast row: 1 job failed or running, 2 expires within 7 days, 3 just evaluated, 5 everything else. */
function tierOf(row, alertSymbols, nowMs) {
  if (alertSymbols.has(row.symbol)) return 1;
  const end = targetEndMs(row);
  if (end !== null && row.expired !== true && end >= nowMs && end - nowMs <= EXPIRY_WINDOW_DAYS * DAY_MS) return 2;
  if (row.expired === true && row.evaluation?.status === "succeeded" && end !== null && nowMs - end <= JUST_EVALUATED_DAYS * DAY_MS) return 3;
  return 5;
}

/**
 * Forecast rows in the order the reader should look at them (design §1.2; the 有可用修订材料 tier is dropped, so
 * tiers are 1, 2, 3 and 5).  Inside a tier: running or failed work newest first, expiring soonest first, evaluated
 * most recent target first, the rest newest first; ties fall back to decision time and then id, so the order is
 * stable.  Rows past their target without a finished evaluation are ordinary rows, not "expiring".
 * @returns {Array<{ row: object, tier: 1 | 2 | 3 | 5 }>}
 */
export function sortForAttention(rows, jobAlerts, now) {
  const nowMs = (asDate(now) ?? new Date()).getTime();
  const alertSymbols = new Set((Array.isArray(jobAlerts) ? jobAlerts : []).map((alert) => alert?.symbol).filter(Boolean));
  const ranked = (Array.isArray(rows) ? rows : []).map((row) => ({ row, tier: tierOf(row, alertSymbols, nowMs) }));
  const within = {
    1: (a, b) => decisionMs(b.row) - decisionMs(a.row),
    2: (a, b) => targetEndMs(a.row) - targetEndMs(b.row),
    3: (a, b) => targetEndMs(b.row) - targetEndMs(a.row),
    5: (a, b) => decisionMs(b.row) - decisionMs(a.row),
  };
  return ranked.sort((a, b) => a.tier - b.tier
    || within[a.tier](a, b)
    || decisionMs(b.row) - decisionMs(a.row)
    || String(a.row.id).localeCompare(String(b.row.id)));
}

const ATTENTION_LABELS = { 1: "任务进行中或未完成", 2: "7 天内到期", 3: "刚完成到期评估", 5: "" };
/** The phrase key explaining why a row sits where it does; empty for ordinary rows. */
export function attentionLabel(tier) {
  return ATTENTION_LABELS[tier] ?? "";
}

/** The filters on offer: 全部 and 研究队列 always, 持仓 only when a portfolio can be read. */
export function filterScopes(hasPortfolio) {
  return hasPortfolio ? ["all", "holdings", "queue"] : ["all", "queue"];
}

function symbolSet(list) {
  return new Set((Array.isArray(list) ? list : []).map((symbol) => String(symbol).toUpperCase()));
}

/** Rows kept by a scope.  An empty holdings list under 持仓 keeps nothing; it never falls back to showing all. */
export function filterRows(rows, scope, holdings, queue) {
  const list = Array.isArray(rows) ? rows : [];
  if (scope === "holdings") { const held = symbolSet(holdings); return list.filter((row) => held.has(String(row.symbol).toUpperCase())); }
  if (scope === "queue") { const queued = symbolSet(queue); return list.filter((row) => queued.has(String(row.symbol).toUpperCase())); }
  return list;
}

/** 持仓 wins over 队列 when a symbol is both; null when it is neither. */
export function symbolMark(symbol, holdings, queue) {
  const key = String(symbol).toUpperCase();
  if (symbolSet(holdings).has(key)) return "持仓";
  if (symbolSet(queue).has(key)) return "队列";
  return null;
}

/** Result line of a judgment, from the defined label only (design §2 rule 7); a phrase key. */
export function judgmentResultText(outcome) {
  switch (outcome?.status) {
    case "matched": return "方向相符";
    case "mismatched": return "方向不符";
    case "no_marked_move": return "未出现明显波动";
    case "not_applicable": return "没有给出方向，不计结果";
    default: return "等待首个交易日收盘";
  }
}

/** Judgments that reached the owner, and the ones the system skipped (kept visible, collapsed). */
export function splitDelivered(judgments) {
  const delivered = [];
  const skipped = [];
  for (const judgment of Array.isArray(judgments) ? judgments : []) (judgment?.delivered ? delivered : skipped).push(judgment);
  return { delivered, skipped };
}

/** Rows grouped by symbol (upper case), each group newest decision first.  One list call feeds every queue card. */
export function forecastBySymbol(rows) {
  const groups = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const key = String(row?.symbol ?? "").toUpperCase();
    if (!key) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  for (const group of groups.values()) group.sort((a, b) => decisionMs(b) - decisionMs(a));
  return groups;
}

/** Symbols that have both a formal forecast and a judgment: the page says the two ask different questions. */
export function symbolsWithBoth(rows, judgments) {
  const judged = new Set((Array.isArray(judgments) ? judgments : []).map((judgment) => judgment.symbol));
  return new Set((Array.isArray(rows) ? rows : []).map((row) => row.symbol).filter((symbol) => judged.has(symbol)));
}

/**
 * What the judgments call became.  A guest has no such lane (401 or 403 hides it, without an error); any other
 * failure is an error the lane can report; a list is a list.  Takes a `Promise.allSettled` result.
 */
export function judgmentLane(settled) {
  if (settled?.status === "fulfilled") return { lane: "ready", judgments: Array.isArray(settled.value) ? settled.value : [] };
  const status = settled?.reason?.status;
  if (status === 401 || status === 403) return { lane: "hidden" };
  return { lane: "error" };
}

function percentText(fraction, signed = false) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  const value = fraction * 100;
  return `${signed && value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

/** Whole-number percents of three probabilities (for plain-text lines); null when there are none. */
export function probabilityPercents(probabilities) {
  if (!probabilities) return null;
  return {
    bearish: Math.round(probabilities.bearish * 100),
    neutral: Math.round(probabilities.neutral * 100),
    bullish: Math.round(probabilities.bullish * 100),
  };
}

/** View model of one formal-forecast row.  It has probabilities and a version, and no direction word. */
export function formalRowModel(row, { holdings, queue } = {}) {
  const decider = row?.decider ?? {};
  return {
    id: row.id,
    symbol: row.symbol,
    mark: symbolMark(row.symbol, holdings, queue),
    titleParts: [{ t: "正式预测 · 第" }, { v: ` ${row.latest_version_no} ` }, { t: "版" }],
    probabilities: row.probabilities ?? null,
    targetDate: row.target_end_date ?? null,
    expired: row.expired === true,
    model: decider.actual_model ?? null,
    modelStatus: row.model_status,
    versionNo: row.latest_version_no,
    hash: `#forecast/${row.id}`,
  };
}

/** View model of one judgment row.  It has no probabilities; its only percentage is the after-hours move it knew. */
export function judgmentRowModel(judgment) {
  const direction = judgment?.direction === "up" ? "偏涨" : judgment?.direction === "down" ? "偏跌" : "没有明确方向";
  const confidence = { high: "把握：高", medium: "把握：中", low: "把握：低" }[judgment?.confidence] ?? null;
  const afterHours = percentText(judgment?.after_hours, true);
  return {
    id: judgment.id,
    symbol: judgment.symbol,
    typeLabel: "财报判断 · 轻量 · 未经盲测",
    typeNote: "只判断发布后首个交易日，不是概率预测，也没有版本和证据冻结。",
    direction,
    confidence,
    time: judgment.accepted_at,
    model: judgment.model ?? null,
    modelFirstStage: judgment.model_source === "first_stage",
    result: judgmentResultText(judgment.outcome),
    afterHours: afterHours === null ? null : { parts: [{ t: "判断时已知盘后" }, { v: ` ${afterHours}` }] },
    delivered: Boolean(judgment.delivered),
    hash: `#forecast/judgment/${judgment.id}`,
  };
}
