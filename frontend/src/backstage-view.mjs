// 后台 (the owner's read-only backstage): what the four tabs show, as plain rows.  Pure: no React, no window, no fetch.
//
// The API's answers (app/backstage_api.py) go in; rows of display text come out.  A phrase that needs translating is returned as its Chinese
// source text (the component passes it through t()); numbers, times and ids are returned ready to print.  Nothing here guesses a value the API
// did not give: a cost the API could not price is 「未设价格」, a missing figure is a dash.
import { toolLabel } from "./agent-tool-labels.mjs";

const DASH = "—";

/**
 * The words a sentence is put together from: the translation function and the punctuation of the interface language.  The default is Chinese as written here
 * (what the tests read); a component passes `{ t, colon: colon(), comma: comma(), list: comma(), parens }` from i18n so a composed line reads right in English too.
 */
export const ZH_WORDS = Object.freeze({ t: (phrase) => phrase, colon: "：", comma: "，", list: "、", parens: (value) => `（${value}）` });
const SEARCH_MAX = 100;

// ---- the shared small formatters ---------------------------------------------------------------------------------

/** "850 ms", "2.5 s", "1 min 2 s"; a dash when there is no figure. */
export function formatMs(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return DASH;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

/** 1,870; a dash when there is no figure. */
export function formatTokens(count) {
  return typeof count === "number" && Number.isFinite(count) ? Math.round(count).toLocaleString("en-US") : DASH;
}

/** A dollar figure: two decimals, four under ten cents (a routine call costs a fraction of a cent), the digits that matter under 0.0001. */
export function formatUsd(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  if (value > 0 && value < 0.0001) return `$${value.toFixed(8).replace(/0+$/, "")}`;
  if (value > 0 && value < 0.1) return `$${value.toFixed(4)}`;
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * The cost cell.  `amount` is a number; `unpriced` is a call (or calls) that used a model with no price set (the page says 「未设价格」, never a figure it made up);
 * `none` is no model call at all.  `hadCalls` says whether anything was called.
 */
export function costCell(cost, hadCalls) {
  if (typeof cost === "number" && Number.isFinite(cost)) return { kind: "amount", amount: formatUsd(cost) };
  return { kind: hadCalls ? "unpriced" : "none", amount: "" };
}

/** "11-13 01:50" in the zone given (the browser's own when none is). */
export function formatTime(value, timeZone) {
  const date = new Date(value ?? "");
  if (value === null || value === undefined || Number.isNaN(date.getTime())) return DASH;
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", ...(timeZone ? { timeZone } : {}) })
    .formatToParts(date).map((part) => [part.type, part.value]));
  return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

const TIERS = { low: "低档", mid: "中档", high: "高档" };
/** 低档 / 中档 / 高档, or a dash. */
export function tierLabel(tier) {
  return TIERS[tier] ?? DASH;
}

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const list = (value) => (Array.isArray(value) ? value : []);
const text = (value) => (typeof value === "string" ? value.trim() : "");

// ---- 回答 ----------------------------------------------------------------------------------------------------------

export const ANSWER_FILTER_DEFAULTS = Object.freeze({ botId: "", engine: "", status: "", highTier: false, slow: false, q: "", before: "" });
export const ANSWER_ENGINES = [{ value: "v2", label: "新流程" }, { value: "v1", label: "旧流程" }];
export const ANSWER_STATUSES = ["succeeded", "failed", "cancelled", "waiting_for_input", "incomplete"];

const STATUS = {
  succeeded: { label: "已回答", kind: "success" },
  failed: { label: "失败", kind: "failure" },
  cancelled: { label: "已取消", kind: "neutral" },
  waiting_for_input: { label: "等你回复", kind: "action" },
  incomplete: { label: "没有完成", kind: "failure" },
};
/** `{ label, kind }` of an answer's status (kind is a StatusBadge kind); an unknown status is shown as it came. */
export function answerStatus(status) {
  return STATUS[status] ?? { label: text(status) || DASH, kind: "neutral" };
}

function paramsOf(entries) {
  const params = new URLSearchParams();
  for (const [key, value] of entries) if (value !== "" && value !== null && value !== undefined && value !== false) params.set(key, String(value));
  const out = params.toString();
  return out ? `?${out}` : "";
}

/** The query string of the answers list: only what is set.  「只看用了高档的」 is tier=high, 「只看慢的」 is slow=1; the search text is cut to the 100 characters the API takes. */
export function answersQuery(filters) {
  const f = { ...ANSWER_FILTER_DEFAULTS, ...filters };
  return paramsOf([["bot_id", f.botId], ["engine", f.engine], ["status", f.status], ["tier", f.highTier ? "high" : ""], ["slow", f.slow ? "1" : ""], ["q", text(f.q).slice(0, SEARCH_MAX)], ["before", f.before]]);
}

/** "?before=<cursor>" for the lists that only page (操作记录, 提醒投递). */
export function pagedQuery(before) {
  return paramsOf([["before", before]]);
}

/** The rule line shown with 「只看慢的」: the API names the p90 it used. */
export function slowRuleText(thresholdMs, w = ZH_WORDS) {
  return typeof thresholdMs === "number" && Number.isFinite(thresholdMs) ? `${w.t("慢的标准：耗时高于本页回答的 90 分位")}${w.parens(formatMs(thresholdMs))}` : "";
}

/** One line of the answers table. */
export function answerRow(item, timeZone, w = ZH_WORDS) {
  const calls = Number(item?.model_calls) || 0;
  const total = Number(item?.tokens?.total) || 0;
  return {
    id: item?.message_id ?? "",
    time: formatTime(item?.created_at, timeZone),
    bot: text(item?.bot_name) || DASH,
    question: text(item?.question) || w.t("（没有问题文字）"),
    status: answerStatus(item?.status),
    tier: w.t(tierLabel(item?.tier)),
    time_taken: formatMs(item?.total_ms),
    calls: calls > 0 ? String(calls) : DASH,
    tokens: total > 0 ? formatTokens(total) : DASH,
    cost: costCell(item?.cost_usd, calls > 0 || total > 0),
    old_engine: item?.engine === "v1",
  };
}

/** The lines above the timeline: an old-engine record, a turn that did not finish, a switch to the backup model. */
export function answerNotes(detail, w = ZH_WORDS) {
  const notes = [];
  if (detail?.engine === "v1") notes.push({ kind: "old_engine", text: w.t("旧流程的记录，只有部分经过") });
  if (detail?.status === "incomplete") notes.push({ kind: "incomplete", text: w.t("这一轮没有答完，下面是它留下的记录") });
  const backup = detail?.backup_model;
  if (isObject(backup) && (backup.from || backup.to)) notes.push({ kind: "backup", text: `${w.t("改用备用模型")}${w.colon}${backup.from ?? DASH} → ${backup.to ?? DASH}${backup.reason ? w.parens(backup.reason) : ""}` });
  return notes;
}

function compactJson(value, max = 600) {
  if (!isObject(value) || Object.keys(value).length === 0) return "";
  let out = "";
  try { out = JSON.stringify(value); } catch { return ""; }
  return out.length > max ? `${out.slice(0, max)}…` : out;
}

function toolResultText(result, w) {
  if (!isObject(result)) return w.t("没有结果记录");
  if (result.ok === false) return `${w.t("失败")}${w.colon}${text(result.error_code) || w.t("未知原因")}`;
  const titles = list(result.row_titles).filter((title) => typeof title === "string" && title);
  return `${w.t("成功")}${typeof result.count === "number" ? `${w.comma}${w.t("共")} ${result.count} ${w.t("条")}` : ""}${titles.length ? `${w.colon}${titles.join(w.list)}` : ""}`;
}

function targetText(target) {
  if (!isObject(target)) return "";
  return text(target.kind) || [text(target.symbol), text(target.title)].filter(Boolean).join(" ");
}

/** The vertical timeline of one turn, in the order it happened: question, narration, model calls, tool calls, the card and what became of it, the answer. */
export function detailTimeline(detail, timeZone, w = ZH_WORDS) {
  if (!isObject(detail)) return [];
  const steps = [];
  if (text(detail.question)) steps.push({ kind: "question", title: w.t("问题"), text: detail.question });
  for (const line of list(detail.narration)) if (text(line)) steps.push({ kind: "narration", title: w.t("过程"), text: line });
  for (const call of list(detail.model_calls)) {
    if (!isObject(call)) continue;
    const total = Number(call.tokens?.total) || 0;
    steps.push({ kind: "model", title: text(call.catalog_name) || text(call.model) || w.t("未知模型"), tier: w.t(tierLabel(call.tier)), purpose: text(call.purpose), attempt: Number(call.attempt) || 1,
      ok: call.ok !== false, error: text(call.error), ms: formatMs(call.ms), tokens: total > 0 ? formatTokens(total) : DASH, cost: costCell(call.cost_usd, total > 0), time: formatTime(call.at, timeZone) });
  }
  for (const call of list(detail.tool_calls)) {
    if (!isObject(call)) continue;
    steps.push({ kind: "tool", title: w.t(toolLabel(call.name)) || w.t("未知工具"), name: text(call.name), arguments: compactJson(call.arguments), state: text(call.status) || "unfinished", result: toolResultText(call.result, w) });
  }
  const card = detail.card;
  if (isObject(card)) {
    const consent = isObject(card.consent) ? card.consent : null;
    const state = consent ? operationStatus({ status: consent.status, expired: consent.expired, decided_at: consent.decided_at }) : null;
    const stateLabel = state ? w.t(state.label) : "";
    steps.push({ kind: "card", title: text(card.title) || w.t("确认卡片"), text: text(card.question), targets: list(card.targets).map(targetText).filter(Boolean),
      choices: list(card.choices).map((choice) => text(choice?.label)).filter(Boolean), state });
    if (consent && state && (consent.status !== "proposed" || consent.expired)) steps.push({ kind: "card_result", title: stateLabel, time: formatTime(consent.decided_at, timeZone), result: operationResultText(consent.result, w) });
  }
  if (text(detail.answer)) steps.push({ kind: "answer", title: w.t("回答"), text: detail.answer });
  return steps;
}

// ---- 用量 ----------------------------------------------------------------------------------------------------------

export const USAGE_GROUPS = [{ value: "day", label: "按天" }, { value: "model", label: "按模型" }, { value: "bot", label: "按 bot" }, { value: "purpose", label: "按用途" }];
export const USAGE_PRESETS = [7, 30];

/** The last `days` UTC days ending at `today` (YYYY-MM-DD), both ends included.  The API's days are UTC days. */
export function usageRange(days, today) {
  const end = new Date(`${today}T00:00:00Z`);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (days - 1));
  return { from: start.toISOString().slice(0, 10), to: today };
}

/** "?from=&to=&group=" with only what is set. */
export function usageQuery({ from, to, group }) {
  return paramsOf([["from", from], ["to", to], ["group", group]]);
}

const PRICE_NAMES = { input: "输入价", output: "输出价", cache_read: "缓存读取价", cache_write: "缓存写入价" };
const PURPOSES = { chat: "对话", summary: "摘要", profile: "画像", judge: "核查", forecast: "预测", earnings: "财报", material_analysis: "材料分析", news: "新闻", routine: "例行任务",
  query_expansion: "查询扩展", localization: "翻译", knowledge: "知识库", other: "其他" };

/** The name of a group: a purpose in words; a day, a model and a bot as the API labels them. */
export function usageGroupLabel(group, row, w = ZH_WORDS) {
  if (group === "purpose") return PURPOSES[row?.key] ? w.t(PURPOSES[row.key]) : text(row?.label) || text(row?.key);
  return text(row?.label) === "（无）" ? w.t("（无）") : text(row?.label) || text(row?.key);
}

function usageFields(g, w) {
  const tokens = isObject(g?.tokens) ? g.tokens : {};
  const calls = Number(g?.calls) || 0;
  return { calls: String(calls), failed: String(Number(g?.failed_calls) || 0), input: formatTokens(tokens.input ?? 0), output: formatTokens(tokens.output ?? 0),
    cache: `${formatTokens(tokens.cache_read ?? 0)} / ${formatTokens(tokens.cache_write ?? 0)}`, p50: formatMs(g?.ms_p50), cost: costCell(g?.cost_usd, calls > 0),
    missing: list(g?.missing_prices).map((name) => w.t(PRICE_NAMES[name] ?? text(name))).filter(Boolean), unpriced_calls: Number(g?.unpriced_calls) || 0 };
}

/** One line of the usage table. */
export function usageRow(g, group, w = ZH_WORDS) {
  return { key: text(g?.key), label: usageGroupLabel(group, g, w), ...usageFields(g, w) };
}

/** The totals line. */
export function usageTotalsRow(totals, w = ZH_WORDS) {
  return { key: "total", label: w.t("合计"), ...usageFields(totals, w) };
}

// ---- 操作记录 ------------------------------------------------------------------------------------------------------

const OPERATION_STATUS = {
  proposed: { label: "等待确认", kind: "action" },
  executing: { label: "执行中", kind: "progress" },
  complete: { label: "已完成", kind: "success" },
  cancelled: { label: "已取消", kind: "neutral" },
  cancelling: { label: "取消中", kind: "progress" },
};

/** A card's state.  A card that lapsed and that nobody decided says so in those words; one pressed after it lapsed is just 已过期. */
export function operationStatus({ status, expired, decided_at: decidedAt }) {
  if (status === "expired" || (status === "proposed" && expired)) return { label: decidedAt ? "已过期" : "已过期，未处理", kind: "neutral" };
  return OPERATION_STATUS[status] ?? { label: text(status) || DASH, kind: "neutral" };
}

function operationResultText(result, w) {
  if (!isObject(result)) return DASH;
  const outcomes = list(result.outcomes).filter(isObject);
  const failed = outcomes.filter((outcome) => outcome.ok === false);
  if (result.ok === false || failed.length) return `${w.t("失败")}${w.colon}${failed.map((outcome) => text(outcome.error_code)).filter(Boolean).join(w.list) || w.t("未知原因")}`;
  return w.t("成功");
}

/** One line of the confirmation cards table. */
export function operationRow(item, timeZone, w = ZH_WORDS) {
  const operations = list(item?.operations).map((operation) => w.t(toolLabel(operation?.name))).filter(Boolean).join(w.list);
  const targets = list(item?.targets).map(targetText).filter(Boolean).join(w.list);
  return {
    id: item?.id ?? "",
    time: formatTime(item?.created_at, timeZone),
    bot: text(item?.bot_name) || DASH,
    what: text(item?.title) || w.t("操作"),
    detail: [operations, targets].filter(Boolean).join(" · "),
    status: operationStatus(item ?? {}),
    decided_at: formatTime(item?.decided_at, timeZone),
    result: operationResultText(item?.result, w),
  };
}

// ---- 提醒投递 ------------------------------------------------------------------------------------------------------

const SOURCES = { notify: "提醒", routine: "任务" };
const CHANNELS = { telegram: "Telegram", wechat: "微信", pushover: "Pushover" };

function deliveryStatus(item) {
  if (item?.status === "sent") return item.failure === "partial" ? { label: "部分送达", kind: "action" } : { label: "已发送", kind: "success" };
  if (item?.status === "pending") return { label: "等待发送", kind: "progress" };
  if (item?.status === "failed") return item.failure === "expired" ? { label: "过期未发", kind: "failure" } : { label: "发送失败", kind: "failure" };
  return { label: text(item?.status) || DASH, kind: "neutral" };
}

/** One line of the outbox table. */
export function deliveryRow(item, timeZone, w = ZH_WORDS) {
  return {
    id: item?.id ?? "",
    time: formatTime(item?.created_at, timeZone),
    source: SOURCES[item?.source] ?? (text(item?.source) || DASH),
    channel: CHANNELS[item?.channel] ?? (text(item?.channel) || DASH),
    status: deliveryStatus(item),
    acked: item?.acked_at ? formatTime(item.acked_at, timeZone) : item?.status === "sent" ? w.t("未确认") : DASH,
    text: text(item?.text),
  };
}
