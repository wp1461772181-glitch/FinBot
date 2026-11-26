// 它眼中的你 (the memory page's overview tab): pure helpers for the summary head, the views section, the memory calendar and the export file name.  The overview itself is
// GET /agent-chat/memory/overview; nothing here changes what the server sent, it only orders and words it.  Wording that carries a number or a date is made for the locale here;
// fixed words go through the page's own t().

import { formatPriceLines } from "./inbox-items.mjs";
import { dayLabel, monthDay } from "./owner-views.mjs";
import { plainNumber } from "./price-lines.mjs";

const byNewest = (list) => (Array.isArray(list) ? list.filter((v) => v && typeof v === "object") : []).sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
const count = (value) => (typeof value === "number" && Number.isFinite(value) ? value : 0);

// The counts shown in the head, in this order: [key, the Chinese label the page translates].
const COUNT_LABELS = [
  ["said", "你说过的"], ["typed", "你写的"], ["inferred", "它推断的"], ["guesses_confirmed", "你确认的推测"], ["guesses_waiting", "待你确认的推测"],
  ["archived", "已归档"], ["views_current", "你的看法"], ["views_companies", "有看法的公司"], ["watch", "在盯的"],
];

/** The head's counts as an ordered list of `{ key, label, value }`.  A zero stays (so "0 条推测" is visible); a missing number is 0; no counts at all is an empty list. */
export function summaryLine(counts) {
  if (!counts || typeof counts !== "object") return [];
  return COUNT_LABELS.map(([key, label]) => ({ key, label, value: count(counts[key]) }));
}

/**
 * The companies of the views section: those with a current (active) view first, newest first; the rest (only ended versions: updated, withdrawn, archived) after them, by their newest
 * version.  Each company is `{ ...company, current, versions, history }`: `versions` newest first (the server's order is not trusted), `history` the versions other than the current one.
 */
export function viewGroups(views) {
  const list = Array.isArray(views) ? views.filter((c) => c && typeof c === "object" && String(c.symbol ?? "").trim()) : [];
  const shaped = list.map((company) => {
    const versions = byNewest([...(Array.isArray(company.versions) ? company.versions : [])]);
    const sent = company.current && typeof company.current === "object" && company.current.status === "active" ? company.current : null;
    const current = sent ?? versions.find((v) => v.status === "active") ?? null;
    return { ...company, current, versions, history: versions.filter((v) => v !== current && v.id !== current?.id) };
  });
  const stamp = (company) => String(company.current?.created_at ?? company.versions[0]?.created_at ?? "");
  const newest = (a, b) => stamp(b).localeCompare(stamp(a));
  return { current: shaped.filter((c) => c.current).sort(newest), former: shaped.filter((c) => !c.current).sort(newest) };
}

/**
 * A view the owner typed on the page has no conversation behind it and its quote is its own text (the page shows 「在记忆页写的」 instead of a link or a quote).  A view with no conversation
 * but a quote of other words is not labelled so: its quote is shown, as it is the basis.
 */
export function typedOnPage(version) {
  if (!version || typeof version !== "object" || version.conversation_id != null) return false;
  const quote = String(version.quote ?? "").trim();
  return !quote || quote === String(version.text ?? "").trim();
}

/** What a refused view write says (the server's detail is a code).  `view_quote_too_short` is the one the owner can fix at once: 「至少写四个字」. */
export function viewWriteError(status, detail) {
  if (status === 403) return "登录个人聊天后才能修改你的看法。";
  if (status === 404) return "这条已不存在。";
  if (status === 422) {
    if (detail === "view_quote_too_short") return "至少写四个字";
    if (detail === "company_not_recognized") return "没认出这家公司。";
    if (detail === "invalid_view_text") return "这条看法没法保存：内容为空或太长。";
  }
  return "保存失败，请重试。";
}

// The memory calendar.
const JOB_NAMES = { monthly_review: ["每月整理", "monthly tidy"], quarterly_settle: ["每季整理", "quarterly tidy"] };

function dateText(value, locale, now) {
  const date = new Date(value ?? "");
  if (Number.isNaN(date.valueOf())) return "";
  const year = (d) => Number(new Intl.DateTimeFormat("en-US", { year: "numeric", timeZone: "Asia/Shanghai" }).format(d));
  const md = monthDay(date);
  if (!md) return "";
  if (year(date) === year(now)) return dayLabel(date, locale);
  return locale === "en-US" ? `${md.month}/${md.day}/${year(date)}` : `${year(date)}年${md.month}月${md.day}日`;
}

/**
 * The line for when the next tidy is due: 「下次每月整理：12月25日前后（再发 N 条消息会提前）」, 「下次每季整理：2027年2月15日」.  The year shows only when it is not this year.  The monthly one is
 * "around" its date and says how many more messages bring it forward when there are some still needed; the quarterly one is on its date.
 */
export function jobLine(job, locale = "zh-CN", now = new Date()) {
  const en = locale === "en-US";
  const names = JOB_NAMES[job?.job];
  const name = names ? names[en ? 1 : 0] : String(job?.title ?? job?.job ?? "").trim();
  const day = dateText(job?.next_due, locale, now);
  const head = en ? `Next ${name}: ` : `下次${name}：`;
  if (!day) return `${head}${en ? "not scheduled yet" : "还没排定"}`;
  const monthly = job?.job === "monthly_review";
  const early = monthly && typeof job?.messages_until_early === "number" && job.messages_until_early > 0 ? job.messages_until_early : 0;
  if (en) return `${head}${monthly ? "around " : ""}${day}${early ? ` (${early} more message${early === 1 ? " brings" : "s bring"} it forward)` : ""}`;
  return `${head}${day}${monthly ? "前后" : ""}${early ? `（再发 ${early} 条消息会提前）` : ""}`;
}

/** How the last tidy ended: 上次整理完成 / 上次跳过：reason / 上次出错，稍后重试; "" when it has not run (or the outcome is not one of these). */
export function jobOutcome(job, locale = "zh-CN") {
  const en = locale === "en-US";
  const reason = String(job?.last_reason ?? "").trim();
  if (job?.last_outcome === "done") return en ? "Last tidy: done" : "上次整理完成";
  if (job?.last_outcome === "skipped") return en ? `Last tidy: skipped${reason ? `: ${reason}` : ""}` : `上次跳过${reason ? `：${reason}` : ""}`;
  if (job?.last_outcome === "failed") return en ? "Last tidy: failed, will retry later" : "上次出错，稍后重试";
  return "";
}

/** The file name the page gives a download: finbot-memory-YYYYMMDD.json (or .md), the UTC date, as the server names it.  Anything but "md" is JSON. */
export function exportFilename(format, now = new Date()) {
  const date = now instanceof Date && !Number.isNaN(now.valueOf()) ? now : new Date();
  return `finbot-memory-${date.toISOString().slice(0, 10).replaceAll("-", "")}.${format === "md" ? "md" : "json"}`;
}

// 它在帮你盯的 (the watch section): the three lists as the page shows them, made from `overview.watch`.  Nothing is dropped: a plan with only text, a paused routine, an empty list all stay (the
// page says 「（没有）」 for an empty list).  A price is written the way the price-line rows write one (plainNumber); a date is the owner's Beijing day and time.
const PLAN_PRICES = [["add_price", "补仓价"], ["stop_price", "止损价"], ["target_price", "目标价"]];
const isObject = (value) => Boolean(value) && typeof value === "object";
const hasValue = (value) => value != null && String(value).trim() !== "";

function dateTimeText(value, locale, now) {
  const day = dateText(value, locale, now);
  if (!day) return "";
  const parts = new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Shanghai" }).formatToParts(new Date(value));
  return `${day} ${parts.find((p) => p.type === "hour")?.value}:${parts.find((p) => p.type === "minute")?.value}`;
}

/**
 * `{ plans, routines, queue, note }`.  A plan: `{ symbol, prices: [{ key, label, value }], text }` (a price that is missing is left out of `prices`).  A routine: `{ id, name, enabled, scope,
 * scopeLabel, symbols, contents: [{ key, label, detail? }], next }` (`next` is "" when it is paused or has no date).  `queue` is the symbols, or null when it was never saved.
 */
export function watchRows(watch, locale = "zh-CN", now = new Date()) {
  const w = isObject(watch) ? watch : {};
  const plans = (Array.isArray(w.plans) ? w.plans : []).filter(isObject).map((plan) => ({
    symbol: String(plan.symbol ?? ""),
    prices: PLAN_PRICES.filter(([key]) => hasValue(plan[key])).map(([key, label]) => ({ key, label, value: plainNumber(plan[key]) })),
    text: String(plan.plan_text ?? "").trim(),
  }));
  const routines = (Array.isArray(w.alert_routines) ? w.alert_routines : []).filter(isObject).map((routine) => {
    const enabled = routine.enabled !== false;
    const priceLines = formatPriceLines(routine.price_lines);
    const contents = [];
    if (routine.filings) contents.push({ key: "filings", label: "新申报" });
    if (routine.news) contents.push({ key: "news", label: "新闻线索" });
    if (priceLines) contents.push({ key: "price_lines", label: "价格线", detail: priceLines });
    return {
      id: String(routine.id ?? ""), name: String(routine.name ?? ""), enabled, scope: String(routine.scope ?? ""),
      scopeLabel: routine.scope === "symbols" ? "指定公司" : routine.scope === "research_queue" ? "研究队列" : String(routine.scope ?? ""),
      symbols: Array.isArray(routine.symbols) ? routine.symbols.map(String) : [], contents, next: enabled ? dateTimeText(routine.next_run_at, locale, now) : "",
    };
  });
  const queue = Array.isArray(w.research_queue) ? w.research_queue.map(String) : null;
  return { plans, routines, queue, note: String(w.default_rules_note ?? "").trim() };
}
