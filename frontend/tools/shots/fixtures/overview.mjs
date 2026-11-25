// 它眼中的你 (GET /agent-chat/memory/overview): built from the fake backend's own state, so a profile edit or a view write shows in the counts and the views at once.  The plans, the memory
// calendar and the block text are fixed; the alert routines and the research queue are the state's own (tasks of kind alerts, the queue).  Invented data.
import { daysAgo } from "./common.mjs";

const PLANS = [{ symbol: "NVDA", plan_text: "财报后观察，目标位 140。", add_price: null, stop_price: "105.00", target_price: "140.00", updated_at: "2026-11-16T03:00:00+00:00" }];

const JOBS = [
  { job: "monthly_review", title: "每月整理记忆", next_due: "2026-12-25T01:00:00+00:00", last_run_at: "2026-11-25T01:00:00+00:00", last_outcome: "done", last_reason: null, messages_until_early: 12 },
  { job: "quarterly_settle", title: "每季整理记忆（含看法复盘）", next_due: "2027-02-15T01:00:00+00:00", last_run_at: "2026-11-22T01:00:00+00:00", last_outcome: "skipped", last_reason: "没有需要整理的条目" },
];

export const SEEN_BLOCK = [
  "【关于你（每轮都读）】",
  "- 长期持有美股科技股，偏好以季度为周期做决策。",
  "- 回答先给结论，再给依据；数字要带出处。",
  "- 涉及买卖时只给参考意见，不要替我下决定。",
  "【我的推测（未经你确认，只影响详略和先后）】",
  "- 看公司时先问最近一季的收入和利润，再问估值。",
  "【你的看法（M-D 说的）】",
  "- NVDA：估值太高，现在不想追",
  "另有 2 条未显示。",
].join("\n");

const newest = (a, b) => String(b.created_at).localeCompare(String(a.created_at));

/** The overview the real route would answer for this state. */
export function memoryOverview(state) {
  const items = state.assistant.profile;
  const count = (status, origin) => items.filter((i) => i.status === status && (origin === undefined || i.origin === origin)).length;
  const symbols = [...new Set(state.views.map((v) => v.symbol))];
  const views = symbols.map((symbol) => {
    const versions = state.views.filter((v) => v.symbol === symbol).sort(newest);
    return { symbol, name: ({ NVDA: "英伟达", TSLA: "特斯拉", AMD: "超威半导体", INTC: "英特尔" })[symbol] ?? symbol, current: versions.find((v) => v.status === "active") ?? null, versions };
  }).sort((a, b) => (b.current ? 1 : 0) - (a.current ? 1 : 0) || newest(a.current ?? a.versions[0], b.current ?? b.versions[0]));
  const alerts = state.tasks.filter((t) => t.kind === "alerts");
  return {
    counts: {
      said: count("active", "explicit"), typed: count("active", "manual"), inferred: count("active", "inferred"), guesses_confirmed: count("active", "pattern"), guesses_waiting: count("proposed"), archived: count("archived"),
      views_current: state.views.filter((v) => v.status === "active").length, views_companies: symbols.length, watch: PLANS.length + alerts.filter((t) => t.enabled).length + state.queue.length,
    },
    views,
    watch: {
      plans: PLANS,
      alert_routines: alerts.map((t) => ({ id: t.id, name: t.name, enabled: t.enabled, scope: t.scope, symbols: t.symbols, filings: t.config?.filings ?? true, news: t.config?.news ?? true, price_lines: t.config?.price_lines ?? [], next_run_at: t.next_run_at, bot_id: t.bot_id })),
      research_queue: state.queue.length ? state.queue : null,
      default_rules_note: "另外，系统默认对你的持仓和研究队列盯价格异动、新公告（哨兵），这些默认规则现在还不能按你单独调整。",
    },
    jobs: JOBS,
    seen_block: items.some((i) => i.status === "active") ? SEEN_BLOCK : null,
    errors: [],
  };
}

/** Pieces the seeded overview state adds to the default state: a 回头看 with a stray figure on NVDA's current view, a view he typed on the page (TSLA). */
export const OVERVIEW_REVIEW = { verdict: "mixed", verdict_label: "部分成立", text: "说完以后股价又涨了一段，但最新一季的增长也确实放缓了，估值的担心有一半说对了。", unmatched_figures: ["37%"], created_at: daysAgo(2),
  basis: { price_then: { date: "2026-11-08", close: 182.4 }, price_now: { date: "2026-11-24", close: 197.15 }, change_pct: 8.1, quarter_label: "FY2027 Q3" } };
