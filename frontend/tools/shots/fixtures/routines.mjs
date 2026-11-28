// 例行任务: scheduled tasks, their recent runs, bot proposals awaiting a decision, and the inbox (briefs + confirmations).
import { BOT, CONVERSATION } from "./ids.mjs";
import { daysAgo, iso, minutesAgo } from "./common.mjs";

const task = (n, fields) => ({ id: `t2000000-0000-4000-8000-${String(n).padStart(12, "0")}`, name: "", kind: "brief", schedule_kind: "weekdays", schedule_time: "08:30", every_value: null, every_unit: null, max_runs: null, runs_done: 0, finished: false,
  timezone: "Asia/Shanghai", bot_id: BOT.finbot, skill_id: null, instruction: null, scope: "research_queue", symbols: [], channel: "inbox", config: { filings: true, news: true }, enabled: true,
  last_run_at: daysAgo(0, 0), next_run_at: "2026-11-16T00:30:00Z", last_status: "ok", last_status_label: "已发布", last_conversation_id: CONVERSATION.finbot, ...fields });

export const TASKS = [
  task(1, { name: "盘前新闻速览", bot_id: BOT.newsbot, last_conversation_id: CONVERSATION.newsbot, runs_done: 38, instruction: "汇总关注列表公司的盘前新闻，列出最值得看的三条。" }),
  task(2, { name: "AAPL 财报跟踪", next_run_at: "2026-11-13T13:00:00Z", bot_id: BOT.applebot, scope: "symbols", symbols: ["AAPL"], schedule_kind: "daily", schedule_time: "21:00", config: { filings: true, news: false }, last_conversation_id: CONVERSATION.applebot, runs_done: 21 }),
  task(3, { name: "价格线提醒", next_run_at: "2026-11-13T03:15:00Z", kind: "alerts", schedule_kind: "hourly", schedule_time: "00:15", scope: "symbols", symbols: ["NVDA", "AAPL"], channel: "telegram", config: { price_lines: [{ symbol: "NVDA", above: 140 }, { symbol: "AAPL", below: 190 }] }, runs_done: 212, last_status_label: "未触发" }),
  task(4, { name: "周日组合复盘", schedule_kind: "every", schedule_time: "19:00", every_value: 1, every_unit: "weeks", max_runs: 8, runs_done: 3, last_run_at: daysAgo(5, 11), next_run_at: "2026-11-15T11:00:00Z", instruction: "检查持仓的价格计划与最近的财报判断，给出下周要关注的事项。" }),
  task(5, { name: "旧的盘后提醒", kind: "alerts", enabled: false, schedule_kind: "daily", schedule_time: "16:30", scope: "symbols", symbols: ["TSLA"], config: { price_lines: [{ symbol: "TSLA", below: 230 }] }, last_status: null, last_status_label: null, last_run_at: daysAgo(30), next_run_at: null }),
];

export const RUNS = [
  { id: "r0000000-0000-4000-8000-000000000001", task_id: TASKS[0].id, task_name: "盘前新闻速览", status: "ok", status_label: "已发布", posted: 1, tokens: 4120, conversation_id: CONVERSATION.newsbot, created_at: daysAgo(0, 0) },
  { id: "r0000000-0000-4000-8000-000000000002", task_id: TASKS[2].id, task_name: "价格线提醒", status: "no_trigger", status_label: "未触发", posted: 0, tokens: 0, conversation_id: null, created_at: minutesAgo(45) },
  { id: "r0000000-0000-4000-8000-000000000003", task_id: TASKS[1].id, task_name: "AAPL 财报跟踪", status: "ok", status_label: "已发布", posted: 1, tokens: 2890, conversation_id: CONVERSATION.applebot, created_at: daysAgo(1, 13) },
  { id: "r0000000-0000-4000-8000-000000000004", task_id: TASKS[0].id, task_name: "盘前新闻速览", status: "failed", status_label: "失败：模型超时", posted: 0, tokens: 380, conversation_id: null, created_at: daysAgo(2, 0) },
];

export const PROPOSALS = [{ id: "pr000000-0000-4000-8000-000000000001", conversation_id: CONVERSATION.reportbot, bot_id: BOT.reportbot, tools: ["create_task"], title: "每周五盘后总结 NVDA 动态", targets: [{ symbol: "NVDA" }],
  detail: "ReportBot 提议新建例行任务：每周五 16:30 总结 NVDA 的新闻与申报。", expires_at: iso(new Date("2026-11-13T09:00:00Z")), expired: false, created_at: minutesAgo(1500) }];

const src = (ordinal, title, url) => ({ ordinal, title, url, source_type: "news", published_at: daysAgo(0, 0) });
export const INBOX = [
  { id: "i0000000-0000-4000-8000-000000000001", section: "confirm", kind: "action", title: "建议抓取并分析 NVDA 最新 10-Q", body: "无人值守的「周日组合复盘」发现 NVDA 有新的 10-Q 还没进材料库，想把它保存并生成分析。写入材料库需要你确认。",
    sources: [], payload: { task_name: "周日组合复盘", display: { title: "抓取并分析 NVDA 10-Q", targets: [{ symbol: "NVDA", form: "10-Q" }] }, confirmation_state: "pending_confirm", action_token: "fixture-ref", short_code: "A1B2" },
    confirmation_state: "pending_confirm", action_token: "fixture-ref", short_code: "A1B2", actions: [{ id: "confirm", label: "确认", kind: "primary" }, { id: "skip", label: "跳过", kind: "secondary" }, { id: "later", label: "稍后", kind: "secondary" }],
    task_id: TASKS[3].id, bot_id: BOT.finbot, posted: false, conversation_id: null, status: "unread", created_at: minutesAgo(300) },
  { id: "i0000000-0000-4000-8000-000000000002", section: "brief", kind: "task_brief", title: "盘前新闻速览", body: "NVDA：多家云厂商上调资本开支指引。\nTSLA：交付数据发布前，分析师预期略低于上季度。\nAAPL：欧盟 App Store 政策调整生效。",
    sources: [src(1, "云厂商上调资本开支指引（示例来源）", "https://example.test/news/capex"), src(2, "交付预期前瞻（示例来源）", "https://example.test/news/deliveries")], payload: { task_name: "盘前新闻速览" },
    task_id: TASKS[0].id, bot_id: BOT.newsbot, posted: true, conversation_id: CONVERSATION.newsbot, status: "unread", created_at: daysAgo(0, 0) },
  { id: "i0000000-0000-4000-8000-000000000003", section: "brief", kind: "filing", title: "NVDA 新申报：10-Q", body: "NVDA 提交了新的季度报告。", sources: [], payload: { event_id: "e0000000-0000-4000-8000-000000000002" },
    task_id: null, bot_id: BOT.reportbot, posted: false, conversation_id: null, status: "read", created_at: daysAgo(11, 1) },
];

// P7.2: what only some pictures and checks need (stateWithRoutines in pages.mjs adds them; the default state stays what it was, so every other page keeps its pixels).
export const EXTRA_TASKS = [
  // One entry with both sides: the old form split it into two lines when it was saved, the new one keeps the same two lines.
  task(6, { name: "NVDA 上下沿提醒", kind: "alerts", schedule_kind: "hourly", schedule_time: "00:30", scope: "symbols", symbols: ["NVDA"], bot_id: BOT.teslabot, config: { filings: false, news: true, price_lines: [{ symbol: "NVDA", above: 150, below: 120.5 }] }, last_status_label: "未触发", runs_done: 6 }),
  // A time zone nobody would put in a short list: it must still show and save unchanged.
  task(7, { name: "悉尼开盘简报", timezone: "Pacific/Chatham", schedule_kind: "daily", schedule_time: "07:45", bot_id: BOT.teslabot, instruction: "开盘前列出隔夜重要变化。", last_status: "failed", last_status_label: "失败：模型超时", runs_done: 2 }),
  // A task saved before price lines were a list: the line is one text, one part of it not a line at all.
  task(8, { name: "旧式价格线", kind: "alerts", schedule_kind: "daily", schedule_time: "21:30", scope: "symbols", symbols: ["NVDA", "AAPL"], bot_id: BOT.applebot, config: { filings: true, news: false, price_lines: "nvda > 150.5; AAPL<180, 腾讯>300" }, last_status: null, last_status_label: null, last_run_at: null }),
];
export const EXTRA_PROPOSALS = [
  { id: "pr000000-0000-4000-8000-000000000002", conversation_id: CONVERSATION.newsbot, bot_id: BOT.newsbot, tools: ["delete_task"], title: "删除任务「盘前新闻速览」", targets: [{ title: "盘前新闻速览" }],
    detail: "NewsBot 提议删除例行任务「盘前新闻速览」：近三次运行都没有新内容。", expires_at: iso(new Date("2026-11-12T09:00:00Z")), expired: true, created_at: minutesAgo(2900) },
];
export const EXTRA_INBOX = [
  { id: "i0000000-0000-4000-8000-000000000004", section: "confirm", kind: "action", title: "建议抓取并分析 AAPL 最新 10-K", body: "无人值守的「AAPL 财报跟踪」发现 AAPL 有新的 10-K 还没进材料库，想把它保存并生成分析。",
    sources: [], payload: { task_name: "AAPL 财报跟踪", display: { title: "抓取并分析 AAPL 10-K", targets: [{ symbol: "AAPL", form: "10-K" }] }, confirmation_state: "pending_confirm", action_token: "fixture-ref-2", short_code: "C3D4" },
    confirmation_state: "pending_confirm", action_token: "fixture-ref-2", short_code: "C3D4", actions: [{ id: "confirm", label: "确认", kind: "primary" }, { id: "skip", label: "跳过", kind: "secondary" }, { id: "later", label: "稍后", kind: "secondary" }],
    task_id: TASKS[1].id, bot_id: BOT.applebot, posted: false, conversation_id: CONVERSATION.applebot, status: "unread", created_at: minutesAgo(120) },
];

// 手上的事 (GET /agent-chat/work, 11-28): one of each state, as work.list_for gives them.
const item = (kind, n, title, status, status_label, fields = {}) => ({ kind, id: `w${n}`, title, status, status_label, started_at: null, started_local: null, ended_at: null, ended_local: null,
  next_run_at: null, next_run_local: null, failure: null, conversation_id: null, ...fields });
export const WORK = [
  item("chat", 1, "回答：英伟达未来两年数据中心的增长前景（深度研究）", "running", "进行中", { started_local: "11-28 16:02", conversation_id: CONVERSATION.newsbot }),
  item("routine", 2, "例行任务：盘前新闻速览", "queued", "排队中", { next_run_local: "11-29 08:30" }),
  item("job", 3, "预测 AAPL", "done", "完成", { started_local: "11-28 14:10", ended_local: "11-28 14:12", conversation_id: CONVERSATION.applebot }),
  item("chat", 4, "回答：美光的委托书要表决哪些提案", "failed", "失败", { started_local: "11-28 11:40", ended_local: "11-28 11:44", failure: "超过 20 分钟还没答完，已经停下" }),
];
