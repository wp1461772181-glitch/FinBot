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
