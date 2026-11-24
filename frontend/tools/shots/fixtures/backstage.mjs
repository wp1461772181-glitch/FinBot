// 后台 (the owner's read-only backstage): sample payloads of the five /backstage endpoints, in the shapes app/backstage_api.py answers.
// Invented content only.  The unit tests (scripts/backstage-view.test.mjs) read these too, so the view model and the pictures are checked against the same samples.
// `state.backstage` carries the switches a page sets: `empty` (nothing recorded), `fail` (every read fails with 500).
import { BOT, CONVERSATION } from "./ids.mjs";

const Q = (n) => `a1000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const M = (n) => `a2000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const TURN = (n) => `a3000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

const item = (fields) => ({ message_id: M(1), conversation_id: CONVERSATION.finbot, bot_id: BOT.finbot, bot_name: "FinBot", created_at: "2026-11-13T01:50:02+00:00", question: "", answer: "",
  engine: "v2", status: "succeeded", tier: "low", models: ["haiku-5.5"], total_ms: 2500, model_calls: 2, tokens: { total: 1870, cache_read: 300, cache_write: 50 }, cost_usd: 0.0123,
  tool_count: 1, write_outcomes: [], write_outcome: null, cost_state: "priced", missing_prices: [], ...fields });

/** A token with no space or break in it, about 300 characters (a pasted link, a hash): it must not widen any table. */
export const LONG_TOKEN = `https://example.test/${"a1b2c3d4".repeat(37)}`;

export const ANSWERS = {
  items: [
    item({ message_id: M(1), question: "TSLA 最近一个季度的营收是多少？", answer: "Tesla 最近一个季度（Q3）营收约 252 亿美元，同比增长 8%。", total_ms: 4200, tool_count: 2 }),
    item({ message_id: M(2), created_at: "2026-11-13T01:20:11+00:00", question: "把 ANT 加入研究队列", answer: "我已提出这个操作，等你在卡片上确认。", status: "waiting_for_input", tier: "mid", models: ["haiku-5.5", "gpt-6.1-terra"],
      total_ms: 9800, model_calls: 3, tokens: { total: 9420, cache_read: 1200, cache_write: 400 }, cost_usd: 0.0841, write_outcomes: ["proposed"], write_outcome: "proposed" }),
    item({ message_id: M(3), created_at: "2026-11-12T14:05:40+00:00", bot_id: BOT.newsbot, bot_name: "NewsBot", question: "今天有什么值得关注的科技新闻？", answer: "", status: "failed", tier: "high", models: ["muse-ember"],
      total_ms: 61500, model_calls: 4, tokens: { total: 31800, cache_read: 0, cache_write: 0 }, cost_usd: null, tool_count: 3, cost_state: "unpriced", missing_prices: ["input", "output"] }),
    item({ message_id: Q(4), created_at: "2026-11-12T09:12:30+00:00", question: "对比一下 NVDA 和 AMD 最近的毛利率", answer: "", engine: null, status: "incomplete", tier: null, models: ["deepseek-flash"],
      total_ms: null, model_calls: 1, tokens: { total: 640, cache_read: 0, cache_write: 0 }, cost_usd: null, tool_count: 0, cost_state: "pending" }),
    item({ message_id: M(5), created_at: "2026-11-10T03:30:00+00:00", question: "（旧流程）AAPL 的市盈率是多少？", answer: "按最近收盘价，AAPL 的市盈率约为 31 倍。", engine: "v1", tier: null, models: [],
      total_ms: null, model_calls: 0, tokens: { total: 0, cache_read: 0, cache_write: 0 }, cost_usd: null, tool_count: 0, cost_state: "none" }),
  ],
  next_before: "1762737000000000.a2000000-0000-4000-8000-000000000005",
  slow_threshold_ms: null, slow_rule: null,
};

/** The first item of the list as the detail endpoint answers it: a turn with two model calls (one retried on the backup), a tool call, a card and the answer. */
export const DETAIL = {
  message_id: M(2), conversation_id: CONVERSATION.finbot, turn_id: TURN(2), bot_id: BOT.finbot, bot_name: "FinBot", created_at: "2026-11-13T01:20:11+00:00", engine: "v2", partial: false,
  status: "waiting_for_input", tier: "mid", total_ms: 9800, question: "把 ANT 加入研究队列",
  model_calls: [
    { tier: "low", model: "m-1", catalog_name: "haiku-5.5", purpose: "chat", ms: 1700, tokens: { input: 0, output: 0, cache_read: 0, cache_write: 0, total: 0 }, attempt: 1, ok: false, error: "http_500", cost_usd: null, priced: false, at: "2026-11-13T01:20:12+00:00" },
    { tier: "low", model: "m-2", catalog_name: "gpt-6.1-terra", purpose: "chat", ms: 3100, tokens: { input: 2200, output: 260, cache_read: 400, cache_write: 200, total: 3060 }, attempt: 2, ok: true, error: null, cost_usd: 0.0312, priced: true, at: "2026-11-13T01:20:15+00:00" },
    { tier: "mid", model: "m-3", catalog_name: "deepseek-flash", purpose: "chat", ms: 2600, tokens: { input: 2800, output: 280, cache_read: 0, cache_write: 0, total: 3080 }, attempt: 1, ok: true, error: null, cost_usd: null, priced: false, at: "2026-11-13T01:20:19+00:00" },
  ],
  model_calls_source: "ledger", cost_state: "unpriced", missing_prices: ["input", "output"],
  ordered: true,
  events: [
    { kind: "model_call", at_ms: null, step: null, index: 0 }, { kind: "model_call", at_ms: 1700, step: 1, index: 1 }, { kind: "narration", at_ms: 1710, step: 1, index: 0 },
    { kind: "tool_call", at_ms: 1720, step: 1, call_id: "call-1" }, { kind: "tool_call", at_ms: 1725, step: 1, call_id: "call-2" }, { kind: "tool_call", at_ms: 1730, step: 1, call_id: "call-3" },
    { kind: "tool_done", at_ms: 2400, step: 1, call_id: "call-1" }, { kind: "tool_done", at_ms: 2500, step: 1, call_id: "call-2" },
    { kind: "model_call", at_ms: 4400, step: 2, index: 2 }, { kind: "narration", at_ms: 4410, step: 2, index: 1 }],
  narration: ["我先看一下 ANT 是不是已经在研究队列里。", "不在队列里，我来提出加入的操作。"],
  checklist: [{ item: "查研究队列", state: "done" }, { item: "提出加入操作", state: "done" }],
  tool_calls: [
    { call_id: "call-1", name: "query_research_queue", arguments: {}, status: "complete", result: { ok: true, error_code: null, count: 7, row_titles: ["AAPL", "TSLA", "NVDA"] } },
    { call_id: "call-2", name: "add_to_research_queue", arguments: { symbol: "ANT" }, status: "failed", result: { ok: false, error_code: "needs_confirmation", count: null, row_titles: [] } },
    { call_id: "call-3", name: "query_sec_filings", arguments: { symbol: "ANT", form: "10-K" }, status: "unfinished", result: null },
  ],
  citations: [{ ordinal: 1, title: "ANT 10-K（2025）", url: "https://sec.example/ant-10k", source_type: "official_filing" }],
  writes: [{ operation: "add_to_research_queue", tier: 1, outcome: "proposed" }], write_outcome: "proposed",
  card: { request_id: "a4000000-0000-4000-8000-000000000001", reason: "write_confirmation", title: "确认以下操作", targets: [{ kind: "ANT · 加入研究队列" }], question: null,
    choices: [{ label: "同意", kind: "confirm" }, { label: "取消", kind: "cancel" }],
    consent: { status: "complete", expired: false, decided_at: "2026-11-13T01:22:40+00:00", operations: [{ name: "add_to_research_queue", tier: 1 }], result: { ok: true, status: "complete", outcomes: [{ ok: true, error_code: null }] } } },
  answer: "我已提出这个操作，等你在卡片上确认。",
  backup_model: { from: "haiku-5.5", to: "gpt-6.1-terra", reason: "http_500" },
  langfuse_url: "https://langfuse.example/trace/abc123",
};

/** A turn of the old engine: whatever it stored, partial. */
export const DETAIL_OLD = {
  message_id: M(5), conversation_id: CONVERSATION.finbot, turn_id: TURN(5), bot_id: BOT.finbot, bot_name: "FinBot", created_at: "2026-11-10T03:30:00+00:00", engine: "v1", partial: true,
  status: "succeeded", tier: null, total_ms: null, question: "（旧流程）AAPL 的市盈率是多少？", model_calls: [], model_calls_source: "none", cost_state: "none", missing_prices: [], ordered: false, events: [], narration: [], checklist: [], tool_calls: [], citations: [],
  writes: [], write_outcome: null, card: null, answer: "按最近收盘价，AAPL 的市盈率约为 31 倍。", backup_model: null, langfuse_url: null,
};

/** A turn that never produced an answer: the question's own id, tool calls without results. */
export const DETAIL_INCOMPLETE = {
  message_id: Q(4), conversation_id: CONVERSATION.finbot, turn_id: TURN(4), bot_id: BOT.finbot, bot_name: "FinBot", created_at: "2026-11-12T09:12:30+00:00", engine: null, partial: true,
  status: "incomplete", tier: null, total_ms: null, question: "对比一下 NVDA 和 AMD 最近的毛利率",
  model_calls: [{ tier: null, model: "m-3", catalog_name: "deepseek-flash", purpose: "chat", ms: 5200, tokens: { input: 600, output: 40, cache_read: 0, cache_write: 0, total: 640 }, attempt: 1, ok: true, error: null, cost_usd: null, priced: false, at: "2026-11-12T09:12:33+00:00" }],
  model_calls_source: "ledger", cost_state: "pending", missing_prices: [], ordered: false,
  events: [{ kind: "model_call", at_ms: null, step: null, index: 0 }, { kind: "tool_call", at_ms: null, step: null, call_id: "call-1" }], narration: [], checklist: [],
  tool_calls: [{ call_id: "call-1", name: "query_financials", arguments: { symbol: "NVDA" }, status: "unfinished", result: null }],
  citations: [], writes: [], write_outcome: null, card: null, answer: "", backup_model: null, langfuse_url: null,
};

const usageGroup = (key, label, fields) => ({ key, label, calls: 0, failed_calls: 0, tokens: { input: 0, output: 0, cache_read: 0, cache_write: 0 }, ms_p50: null, cost_usd: null, unpriced_calls: 0, missing_prices: [], ...fields });

const GROUPS = {
  day: [
    usageGroup("2026-11-11", "2026-11-11", { calls: 31, failed_calls: 1, tokens: { input: 82000, output: 9100, cache_read: 40000, cache_write: 6000 }, ms_p50: 1800, cost_usd: 0.31 }),
    usageGroup("2026-11-12", "2026-11-12", { calls: 52, failed_calls: 3, tokens: { input: 140000, output: 16800, cache_read: 61000, cache_write: 9000 }, ms_p50: 2100, cost_usd: 0.52, unpriced_calls: 6, missing_prices: ["cache_read", "cache_write"] }),
    usageGroup("2026-11-13", "2026-11-13", { calls: 18, failed_calls: 0, tokens: { input: 40000, output: 5100, cache_read: 9000, cache_write: 1200 }, ms_p50: 1500, cost_usd: 0.12 }),
  ],
  model: [
    usageGroup("haiku-5.5", "haiku-5.5", { calls: 60, failed_calls: 4, tokens: { input: 150000, output: 18000, cache_read: 70000, cache_write: 9000 }, ms_p50: 1700, cost_usd: 0.42 }),
    usageGroup("gpt-6.1-terra", "gpt-6.1-terra", { calls: 30, failed_calls: 0, tokens: { input: 80000, output: 9000, cache_read: 30000, cache_write: 6000 }, ms_p50: 2600, cost_usd: 0.46 }),
    usageGroup("deepseek-flash", "deepseek-flash", { calls: 11, failed_calls: 0, tokens: { input: 32000, output: 4000, cache_read: 10000, cache_write: 2200 }, ms_p50: 3800, cost_usd: null, unpriced_calls: 11, missing_prices: ["cache_read", "cache_write", "input", "output"] }),
  ],
  bot: [
    usageGroup(BOT.finbot, "FinBot", { calls: 70, failed_calls: 3, tokens: { input: 190000, output: 22000, cache_read: 80000, cache_write: 11000 }, ms_p50: 1900, cost_usd: 0.7, unpriced_calls: 6, missing_prices: ["cache_read", "cache_write"] }),
    usageGroup(BOT.newsbot, "NewsBot", { calls: 21, failed_calls: 1, tokens: { input: 52000, output: 7000, cache_read: 25000, cache_write: 4000 }, ms_p50: 2400, cost_usd: 0.18 }),
    usageGroup("none", "（无）", { calls: 10, failed_calls: 0, tokens: { input: 20000, output: 2000, cache_read: 5000, cache_write: 1200 }, ms_p50: 1200, cost_usd: 0.07 }),
  ],
  purpose: [
    usageGroup("chat", "chat", { calls: 68, failed_calls: 4, tokens: { input: 170000, output: 20000, cache_read: 70000, cache_write: 10000 }, ms_p50: 2000, cost_usd: 0.6 }),
    usageGroup("judge", "judge", { calls: 20, failed_calls: 0, tokens: { input: 60000, output: 6000, cache_read: 30000, cache_write: 5000 }, ms_p50: 1500, cost_usd: 0.25 }),
    usageGroup("forecast", "forecast", { calls: 13, failed_calls: 0, tokens: { input: 32000, output: 5000, cache_read: 10000, cache_write: 1400 }, ms_p50: 5200, cost_usd: 0.1, unpriced_calls: 11, missing_prices: ["input", "output"] }),
  ],
};

/** The usage answer for a grouping (the dates are whatever was asked; the sample's numbers do not change with them). */
export function usageAnswer(group = "day", from = "2026-11-07", to = "2026-11-13") {
  const groups = GROUPS[group] ?? GROUPS.day;
  const sum = (pick) => groups.reduce((total, row) => total + pick(row), 0);
  return { from, to, group: GROUPS[group] ? group : "day", timezone: "UTC", timezone_note: "No owner timezone is configured, so days are UTC days (00:00 to 24:00 UTC).",
    totals: { calls: sum((r) => r.calls), failed_calls: sum((r) => r.failed_calls),
      tokens: { input: sum((r) => r.tokens.input), output: sum((r) => r.tokens.output), cache_read: sum((r) => r.tokens.cache_read), cache_write: sum((r) => r.tokens.cache_write) },
      ms_p50: 1900, cost_usd: Math.round(sum((r) => r.cost_usd ?? 0) * 100) / 100, unpriced_calls: sum((r) => r.unpriced_calls), missing_prices: ["cache_read", "cache_write", "input", "output"] },
    groups };
}

export const OPERATIONS = {
  items: [
    { id: "a5000000-0000-4000-8000-000000000001", conversation_id: CONVERSATION.finbot, bot_id: BOT.finbot, bot_name: "FinBot", created_at: "2026-11-13T01:20:20+00:00", expires_at: "2026-11-13T01:30:20+00:00",
      title: "确认以下操作", targets: [{ symbol: "ANT", title: "加入研究队列" }], operations: [{ name: "add_to_research_queue", tier: 1 }], status: "complete", expired: false,
      decided_at: "2026-11-13T01:22:40+00:00", result: { ok: true, status: "complete", outcomes: [{ ok: true, error_code: null }] } },
    { id: "a5000000-0000-4000-8000-000000000002", conversation_id: CONVERSATION.finbot, bot_id: BOT.finbot, bot_name: "FinBot", created_at: "2026-11-12T12:00:00+00:00", expires_at: "2026-11-12T12:10:00+00:00",
      title: "确认以下操作", targets: [{ title: "设置可用资金 · 12345.00" }], operations: [{ name: "set_available_funds", tier: 2 }], status: "proposed", expired: true, decided_at: null, result: null },
    { id: "a5000000-0000-4000-8000-000000000003", conversation_id: CONVERSATION.teslabot, bot_id: BOT.teslabot, bot_name: "TeslaBot", created_at: "2026-11-12T08:40:00+00:00", expires_at: "2026-11-12T08:50:00+00:00",
      title: "确认以下操作", targets: [{ symbol: "TSLA", title: "记录买入 10 股" }], operations: [{ name: "record_trade", tier: 2 }], status: "cancelled", expired: false, decided_at: "2026-11-12T08:41:10+00:00", result: null },
    { id: "a5000000-0000-4000-8000-000000000004", conversation_id: CONVERSATION.finbot, bot_id: BOT.finbot, bot_name: "FinBot", created_at: "2026-11-11T08:40:00+00:00", expires_at: "2026-11-11T08:50:00+00:00",
      title: "确认以下操作", targets: [{ symbol: "NVDA", title: "保存持仓计划" }], operations: [{ name: "set_position_plan", tier: 2 }], status: "complete", expired: false, decided_at: "2026-11-11T08:42:00+00:00",
      result: { ok: false, status: "complete", outcomes: [{ ok: false, error_code: "invalid_price" }] } },
  ],
  next_before: null,
};

export const DELIVERIES = {
  items: [
    { id: "a6000000-0000-4000-8000-000000000001", group_id: null, bot_id: BOT.finbot, source: "notify", channel: "telegram", status: "sent", failure: null, created_at: "2026-11-13T01:00:00+00:00", sent_at: "2026-11-13T01:00:02+00:00", acked_at: "2026-11-13T01:05:00+00:00", text: "NVDA 上穿了你设的 125 美元价格线。" },
    { id: "a6000000-0000-4000-8000-000000000002", group_id: null, bot_id: BOT.newsbot, source: "routine", channel: "wechat", status: "sent", failure: null, created_at: "2026-11-12T23:30:00+00:00", sent_at: "2026-11-12T23:30:05+00:00", acked_at: null, text: "盘前新闻速览已发布：3 条与关注公司相关。" },
    { id: "a6000000-0000-4000-8000-000000000003", group_id: null, bot_id: BOT.finbot, source: "notify", channel: "telegram", status: "failed", failure: "send_failed", created_at: "2026-11-12T10:00:00+00:00", sent_at: null, acked_at: null, text: "AAPL 财报将在今晚发布。" },
    { id: "a6000000-0000-4000-8000-000000000004", group_id: null, bot_id: BOT.finbot, source: "notify", channel: "telegram", status: "failed", failure: "expired", created_at: "2026-11-11T10:00:00+00:00", sent_at: null, acked_at: null, text: "（过期未发）TSLA 跌破止损线。" },
    { id: "a6000000-0000-4000-8000-000000000005", group_id: null, bot_id: BOT.finbot, source: "notify", channel: "telegram", status: "pending", failure: null, created_at: "2026-11-13T01:59:00+00:00", sent_at: null, acked_at: null, text: "等待发送的提醒。" },
  ],
  next_before: null,
};

const duty = (n, fields) => ({ id: n, created_at: "2026-11-13T01:40:00+00:00", alert_id: 100 + n, symbol: "NVDA", kind: "price_move", what: "", mode: "shadow", outcome: "decided", decision: "record",
  reason: null, message: null, delivery: null, turn_id: TURN(n), message_id: null, ms: 8200, model_calls: 3, ...fields });

/** The duty log (/backstage/duty): one row of each decision and each way a wake-up can end; the first opens the full course sample in the drawer. */
export const DUTY = {
  mode: "shadow",
  items: [
    duty(1, { what: "NVDA 盘中下跌 6.2%，跌破 20 日均线", decision: "tell_now", reason: "跌幅大，并且你持有 NVDA。", message: "NVDA 盘中下跌 6.2%，已跌破 20 日均线；你的持仓约占组合的 14%。", message_id: DETAIL.message_id }),
    duty(2, { created_at: "2026-11-13T01:10:00+00:00", symbol: "TSLA", what: "TSLA 上涨 3.1%", decision: "digest", reason: "幅度不大，留到晚上的简报里说。" }),
    duty(3, { created_at: "2026-11-13T00:50:00+00:00", symbol: "AAPL", what: "AAPL 提交了 8-K", decision: "record", reason: "只是例行的董事会变动公告。" }),
    duty(4, { created_at: "2026-11-12T23:20:00+00:00", symbol: "MSFT", what: "MSFT 成交量放大", decision: "ignore", reason: "没有新闻，也没有价格变化。" }),
    duty(5, { created_at: "2026-11-12T22:00:00+00:00", what: "NVDA 单日下跌 5.5%", mode: "on", decision: "tell_now", reason: "跌幅大。", message: "NVDA 单日下跌 5.5%。", delivery: "queued" }),
    duty(6, { created_at: "2026-11-12T21:30:00+00:00", what: "NVDA 再次下跌 5%", mode: "on", decision: "tell_now", reason: "又一次大跌。", message: "NVDA 再次下跌 5%。", delivery: "capped" }),
    duty(7, { created_at: "2026-11-12T20:00:00+00:00", what: "AMZN 财报日期变动", mode: "on", decision: "tell_now", reason: "日期提前。", message: "AMZN 财报提前到周四。", delivery: "telegram_not_bound" }),
    duty(8, { created_at: "2026-11-12T19:00:00+00:00", symbol: "GOOG", what: "GOOG 价格提醒", outcome: "failed", decision: null, reason: "模型超时（120 秒）。", turn_id: null }),
    duty(9, { created_at: "2026-11-12T18:00:00+00:00", symbol: "META", what: "META 价格提醒", outcome: "no_decision", decision: null, reason: "模型没有给出决定。" }),
    duty(10, { created_at: "2026-11-12T17:00:00+00:00", symbol: "AMD", what: "AMD 价格提醒", outcome: "dropped", decision: null, reason: "等待的提醒超过 50 条，这一条被丢弃。", turn_id: null }),
    duty(11, { created_at: "2026-11-12T16:00:00+00:00", symbol: "INTC", what: "INTC 价格提醒", mode: "off", outcome: "skipped_off", decision: null, reason: "唤醒功能关着（FINBOT_DUTY_MODE=off），没有评判。", turn_id: null }),
  ],
  next_before: null,
};

/** The reads, with the page's switches (state.backstage: empty, fail). */
export function backstageRoutes(route, reply, own) {
  const guarded = (answer) => own(({ state, query, params }) => {
    if (state.backstage?.fail) return reply.status(500, { detail: "shots: forced failure" });
    return answer({ state, query, params });
  });
  route.get("/backstage/answers", guarded(({ state, query }) => {
    if (state.backstage?.empty) return { items: [], next_before: null, slow_threshold_ms: null, slow_rule: null };
    const asked = (name) => query.get(name) || "";
    // The first page says there is more; the page after it holds one more row and ends (so the infinite scroll stops).
    if (asked("before")) return { items: [item({ message_id: M(6), created_at: "2026-11-09T09:00:00+00:00", question: "NVDA 下个季度的指引是多少？", answer: "管理层给的指引是营收约 540 亿美元。" })], next_before: null, slow_threshold_ms: null, slow_rule: null };
    const long = state.backstage?.long ? [item({ message_id: M(7), created_at: "2026-11-13T01:55:00+00:00", question: LONG_TOKEN, answer: LONG_TOKEN, bot_name: LONG_TOKEN.slice(0, 60) })] : [];
    const items = [...long, ...ANSWERS.items].filter((row) => (!asked("status") || row.status === asked("status")) && (!asked("engine") || row.engine === asked("engine")) && (!asked("tier") || row.tier === asked("tier")));
    if (asked("slow")) return { items: items.filter((row) => (row.total_ms ?? 0) > 4000), next_before: null, slow_threshold_ms: 4000, slow_rule: "total_ms above the p90 of the turns in this page's window" };
    return { ...ANSWERS, items, next_before: items.length >= ANSWERS.items.length ? ANSWERS.next_before : null };
  }));
  route.get("/backstage/answers/:id", guarded(({ params }) => {
    const found = [DETAIL, DETAIL_OLD, DETAIL_INCOMPLETE].find((d) => d.message_id === params.id);
    return found ?? reply.status(404, { detail: "not_found" });
  }));
  route.get("/backstage/usage", guarded(({ state, query }) => {
    if (state.backstage?.empty) return { ...usageAnswer("day"), totals: { calls: 0, failed_calls: 0, tokens: { input: 0, output: 0, cache_read: 0, cache_write: 0 }, ms_p50: null, cost_usd: null, unpriced_calls: 0, missing_prices: [] }, groups: [] };
    return usageAnswer(query.get("group") || "day", query.get("from") || undefined, query.get("to") || undefined);
  }));
  route.get("/backstage/operations", guarded(({ state }) => {
    if (state.backstage?.empty) return { items: [], next_before: null };
    return state.backstage?.long ? { items: [{ ...OPERATIONS.items[0], id: "a5000000-0000-4000-8000-000000000009", title: LONG_TOKEN, targets: [{ title: LONG_TOKEN }] }, ...OPERATIONS.items], next_before: null } : OPERATIONS;
  }));
  route.get("/backstage/duty", guarded(({ state }) => {
    if (state.backstage?.empty) return { mode: state.backstage.mode ?? "shadow", items: [], next_before: null };
    const mode = state.backstage?.mode ?? DUTY.mode;
    return state.backstage?.long ? { ...DUTY, mode, items: [duty(99, { what: LONG_TOKEN, reason: LONG_TOKEN, message: LONG_TOKEN, decision: "tell_now", symbol: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", message_id: DETAIL.message_id }), ...DUTY.items] } : { ...DUTY, mode };
  }));
  route.get("/backstage/deliveries", guarded(({ state }) => {
    if (state.backstage?.empty) return { items: [], next_before: null };
    return state.backstage?.long ? { items: [{ ...DELIVERIES.items[0], id: "a6000000-0000-4000-8000-000000000009", text: LONG_TOKEN }, ...DELIVERIES.items], next_before: null } : DELIVERIES;
  }));
}
