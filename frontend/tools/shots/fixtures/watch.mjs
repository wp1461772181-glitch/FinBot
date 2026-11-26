// 它在帮你盯的 → 规则 (stage 5b-2, GET /agent-chat/watch): the owner's own rules, the system defaults already resolved with his changes, and the sensitivity.  The shapes are the plan's contract
// (docs/superpowers/plans/2026-11-26-stage5b2-preset-rules.md); the sentences are invented but worded the way the server's code writes them.  The write routes (index.mjs) change `state.watch`.

const OWNER_RULES = [
  { id: "wr-0000-4000-8000-000000000001", symbol: "INTC", metric: "day_change", direction: "down", levels: [{ threshold: 8, level: "remind" }], text: "英特尔单日下跌超过 8%：提醒。当天只提醒一次。", status: "active", last_fired: "11-24 22:40（北京时间）", overrides_default: "默认的下跌分级对它不生效" },
  { id: "wr-0000-4000-8000-000000000002", symbol: "NVDA", metric: "position_weight", direction: "above", levels: [{ threshold: 40, level: "urgent" }], text: "英伟达占总资产超过 40%：加急。条件成立时提醒一次，回到 40% 以下后再超过会再提醒。", status: "active", last_fired: "近 7 天没有触发", overrides_default: null },
  { id: "wr-0000-4000-8000-000000000003", symbol: "AMD", metric: "price", direction: "above", levels: [{ threshold: 180, level: "remind" }], text: "超威半导体涨到 180 美元以上：提醒。有效到 11-20。", status: "expired", last_fired: "近 7 天没有触发", overrides_default: null },
];

const preset = (key, title, text, extra = {}) => ({ key, title, text, enabled: true, levels: null, editable: false, hard_guarantee: false, applies_to: null, yields_on: [], changed: false, ...extra });

const PRESETS = [
  preset("day_moves", "涨跌分级", "按每只股票自己的日波动幅度（σ）分档：约 2σ 值得提醒，4σ 算重大。灵敏度见下面。", { applies_to: ["持仓", "研究队列"], yields_on: ["INTC"] }),
  preset("short_moves", "5 分钟急动", "持仓在 5 分钟内的急动提醒：关。开关在下面。", { enabled: false, applies_to: ["持仓"] }),
  preset("plan_prices", "持仓计划里的价位线", "补仓价、止损价、目标价到了就提醒。价位在持仓计划里改。", { applies_to: ["NVDA"] }),
  preset("stop_price", "止损价", "跌到你写的止损价，立刻加急提醒。这条是硬保证，不能关。", { hard_guarantee: true, applies_to: ["NVDA"] }),
  preset("filings", "新公告（SEC 申报）", "你的持仓和研究队列有新申报，就提醒。这条是硬保证，不能关。", { hard_guarantee: true }),
  preset("concentration", "单只占比过高", "单只持仓占总资产超过 25%：提醒。条件成立时提醒一次，回到 25% 以下后再超过会再提醒。", { levels: [{ threshold: 25, level: "remind" }], editable: true, applies_to: ["INTC", "NVDA", "TSLA"], yields_on: ["NVDA"] }),
  preset("portfolio_drawdown", "组合单日大跌", "组合今天跌超过 3%：提醒；超过 5%：加急。", { levels: [{ threshold: 3, level: "remind" }, { threshold: 5, level: "urgent" }], editable: true, applies_to: "整个组合" }),
  preset("down_streak", "连续下跌", "连续 5 个交易日收盘低于前一天：提醒。", { enabled: false, levels: [{ threshold: 5, level: "remind" }], editable: true, changed: true, applies_to: ["持仓", "研究队列"] }),
  preset("new_high_52w", "创 52 周新高", "价格创下近 252 个交易日的最高收盘：提醒。", { levels: [{ threshold: 0, level: "remind" }], editable: true, applies_to: ["持仓", "研究队列"] }),
  preset("new_low_52w", "创 52 周新低", "价格创下近 252 个交易日的最低收盘：提醒。", { levels: [{ threshold: 0, level: "remind" }], editable: true, applies_to: ["持仓", "研究队列"] }),
  preset("volume_surge", "持仓异常放量", "持仓的成交量超过平时的 3 倍：提醒。", { levels: [{ threshold: 3, level: "remind" }], editable: true, applies_to: ["INTC", "NVDA", "TSLA"] }),
];

const THRESHOLDS = { quiet: [2.5, 5], standard: [2, 4], sensitive: [1.5, 3] };
const DEFAULT_LEVELS = { concentration: [25], portfolio_drawdown: [3, 5], down_streak: [5], volume_surge: [3] };
const TEXTS = {
  concentration: ([a]) => `单只持仓占总资产超过 ${a}%：提醒。条件成立时提醒一次，回到 ${a}% 以下后再超过会再提醒。`,
  portfolio_drawdown: ([a, b]) => `组合今天跌超过 ${a}%：提醒；超过 ${b}%：加急。`,
  down_streak: ([a]) => `连续 ${a} 个交易日收盘低于前一天：提醒。`,
  volume_surge: ([a]) => `持仓的成交量超过平时的 ${a} 倍：提醒。`,
};

export function buildWatch() {
  return { rules: structuredClone(OWNER_RULES), presets: structuredClone(PRESETS), settings: { sensitivity: "standard", short_moves: false }, writes: [] };
}
/** No rule of his own yet; the defaults are the system's. */
export function buildWatchNoRules() {
  const watch = buildWatch();
  watch.rules = [];
  for (const row of watch.presets) row.yields_on = [];
  return watch;
}

/** GET /agent-chat/watch. */
export function watchView(state) {
  const { rules, presets, settings } = state.watch;
  return { rules, presets, settings: { ...settings, thresholds: THRESHOLDS } };
}

/** PATCH /agent-chat/watch-presets/:key: a refusal is `{ status, detail }`, else the row. */
export function patchPreset(state, key, body) {
  const row = state.watch.presets.find((p) => p.key === key);
  if (!row) return { status: 400, detail: "没有这条系统默认。" };
  if (row.hard_guarantee) return { status: 400, detail: "这条是硬保证，不能关。" };
  if (!row.editable) return { status: 400, detail: "这条默认不在这里调整。" };
  if (typeof body?.enabled === "boolean") row.enabled = body.enabled;
  if (Array.isArray(body?.levels)) {
    if (body.levels.some((l) => !(Number(l.threshold) > 0)) && !["new_high_52w", "new_low_52w"].includes(key)) return { status: 400, detail: "门槛要大于 0。" };
    row.levels = body.levels.map((l) => ({ threshold: Number(l.threshold), level: l.level }));
    if (TEXTS[key]) row.text = TEXTS[key](row.levels.map((l) => l.threshold));
  }
  row.changed = true;
  return { row };
}

/** POST /agent-chat/watch-presets/:key/reset. */
export function resetPreset(state, key) {
  const row = state.watch.presets.find((p) => p.key === key);
  const base = PRESETS.find((p) => p.key === key);
  if (!row || !base) return { status: 400, detail: "没有这条系统默认。" };
  if (row.hard_guarantee) return { status: 400, detail: "这条是硬保证，不能关。" };
  Object.assign(row, { enabled: true, changed: false, levels: structuredClone(base.levels), text: DEFAULT_LEVELS[key] && TEXTS[key] ? TEXTS[key](DEFAULT_LEVELS[key]) : base.text });
  return { row };
}
