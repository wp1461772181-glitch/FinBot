// 它在帮你盯的 → 规则 (stage 5b-2, GET /agent-chat/watch): the owner's own rules, the system defaults already resolved with his changes, and the sensitivity.  The shapes are the plan's contract
// (docs/superpowers/plans/2026-11-26-stage5b2-preset-rules.md); the sentences are invented but worded the way the server's code writes them.  The write routes (index.mjs) change `state.watch`.

// Taken from the server's own view (app.watch_rules_view.watch_view) in a test database, so the shapes and sentences are the real ones.
const OWNER_RULES = [
 {
  "id": "25c9d5af-f12d-47ba-8ddf-07d7743f5617",
  "symbol": "INTC",
  "metric": "day_change",
  "direction": "down",
  "levels": [
   {
    "threshold": 8,
    "level": "remind"
   },
   {
    "threshold": 15,
    "level": "urgent"
   }
  ],
  "text": "英特尔相对昨收下跌达到 8%：提醒；达到 15%：加急。每天每档一次。",
  "status": "active",
  "last_fired": "11-24 22:40（北京时间）",
  "overrides_default": "默认的下跌分级对它不生效",
  "created_on": "2026-11-26",
  "expires_on": null
 },
 {
  "id": "244d28c2-f728-4075-8de2-4bd0575e0910",
  "symbol": "INTC",
  "metric": "position_weight",
  "direction": "above",
  "levels": [
   {
    "threshold": 40,
    "level": "urgent"
   }
  ],
  "text": "英特尔占你总资产的比例高于 40%：加急。条件成立时提醒一次，回到 40%以下后再升破会再提醒；每天最多一次。",
  "status": "active",
  "last_fired": "近 7 天没有触发",
  "overrides_default": "系统默认的「单只占比过高」在 INTC 上让位给这条",
  "created_on": "2026-11-26",
  "expires_on": null
 },
 {
  "id": "e8464b10-c8df-441a-bd31-8c2cb7a94c7e",
  "symbol": "AMD",
  "metric": "price",
  "direction": "above",
  "levels": [
   {
    "threshold": 180,
    "level": "remind"
   }
  ],
  "text": "超微的股价高于 180 美元：提醒。条件成立时提醒一次，回到 180 美元以下后再升破会再提醒；每天最多一次。有效到 2026-11-20。",
  "status": "expired",
  "last_fired": "近 7 天没有触发",
  "overrides_default": null,
  "created_on": "2026-11-26",
  "expires_on": "2026-11-20"
 }
];

const PRESETS = [
 {
  "key": "concentration",
  "title": "单只占比过高",
  "text": "每只持仓占你总资产的比例高于 25%：提醒。条件成立时提醒一次，回到 25%以下后再升破会再提醒；每天最多一次。",
  "enabled": true,
  "levels": [
   {
    "threshold": 25,
    "level": "remind"
   }
  ],
  "editable": true,
  "hard_guarantee": false,
  "applies_to": "所有持仓",
  "yields_on": [
   "INTC"
  ],
  "changed": false,
  "threshold_editable": true,
  "unit": "%"
 },
 {
  "key": "portfolio_drawdown",
  "title": "组合当日大跌",
  "text": "你的组合今天的涨跌（所有持仓现有股数 × 相对昨收的价差，合计占昨收时总资产的比例）下跌达到 3%：提醒；达到 5%：加急。每天每档一次。",
  "enabled": true,
  "levels": [
   {
    "threshold": 3,
    "level": "remind"
   },
   {
    "threshold": 5,
    "level": "urgent"
   }
  ],
  "editable": true,
  "hard_guarantee": false,
  "applies_to": "整个组合",
  "yields_on": [],
  "changed": false,
  "threshold_editable": true,
  "unit": "%"
 },
 {
  "key": "down_streak",
  "title": "连续下跌",
  "text": "持仓和研究队列里的每只股票连续下跌（每个交易日收盘低于前一日，今天股价低于昨收也算一天）达到 5 个交易日：提醒。条件成立时提醒一次，连续下跌中断后再连跌到 5 个交易日会再提醒；每天最多一次。",
  "enabled": false,
  "levels": [
   {
    "threshold": 5,
    "level": "remind"
   }
  ],
  "editable": true,
  "hard_guarantee": false,
  "applies_to": "持仓和研究队列",
  "yields_on": [],
  "changed": true,
  "threshold_editable": true,
  "unit": "天"
 },
 {
  "key": "new_high_52w",
  "title": "52 周新高",
  "text": "持仓和研究队列里的每只股票的股价创 52 周新高（不低于过去一年（约 250 个交易日）的最高收盘价）：提醒。同一只股票一个月（20 个交易日）内最多提醒一次。",
  "enabled": true,
  "levels": [
   {
    "threshold": 0,
    "level": "remind"
   }
  ],
  "editable": true,
  "hard_guarantee": false,
  "applies_to": "持仓和研究队列",
  "yields_on": [],
  "changed": false,
  "threshold_editable": false,
  "unit": null
 },
 {
  "key": "new_low_52w",
  "title": "52 周新低",
  "text": "持仓和研究队列里的每只股票的股价创 52 周新低（不高于过去一年（约 250 个交易日）的最低收盘价）：提醒。同一只股票一个月（20 个交易日）内最多提醒一次。",
  "enabled": true,
  "levels": [
   {
    "threshold": 0,
    "level": "remind"
   }
  ],
  "editable": true,
  "hard_guarantee": false,
  "applies_to": "持仓和研究队列",
  "yields_on": [],
  "changed": false,
  "threshold_editable": false,
  "unit": null
 },
 {
  "key": "volume_surge",
  "title": "成交量异常放大",
  "text": "每只持仓今天的成交量（只看常规交易时段，按开盘后已过去的时间折算；开盘后 30 分钟内不判断）相对近 20 个交易日的日均量达到 3 倍：提醒。每天最多一次。",
  "enabled": true,
  "levels": [
   {
    "threshold": 3,
    "level": "remind"
   }
  ],
  "editable": true,
  "hard_guarantee": false,
  "applies_to": "所有持仓",
  "yields_on": [],
  "changed": false,
  "threshold_editable": true,
  "unit": "倍"
 },
 {
  "key": "day_tiers",
  "title": "涨跌分级",
  "text": "涨跌分级：按每只股票自己的日波动幅度（σ）分档，现在的灵敏度是「标准」：约 2σ 提醒、4σ 重大。你为INTC（下跌）定了自己的涨跌规则，默认的分级在这些方向上对它们不生效。",
  "enabled": true,
  "levels": null,
  "editable": false,
  "hard_guarantee": false,
  "applies_to": "持仓和研究队列",
  "yields_on": [
   "INTC"
  ],
  "changed": false,
  "threshold_editable": false,
  "unit": null
 },
 {
  "key": "short_moves",
  "title": "5 分钟急动",
  "text": "5 分钟急动提醒：关。",
  "enabled": false,
  "levels": null,
  "editable": false,
  "hard_guarantee": false,
  "applies_to": "持仓和研究队列",
  "yields_on": [],
  "changed": false,
  "threshold_editable": false,
  "unit": null
 },
 {
  "key": "plan_prices",
  "title": "计划价位（补仓价、目标价）",
  "text": "持仓计划里的补仓价和目标价：你还没写。价位在持仓计划里改。",
  "enabled": true,
  "levels": null,
  "editable": false,
  "hard_guarantee": false,
  "applies_to": "写了计划价位的持仓",
  "yields_on": [],
  "changed": false,
  "threshold_editable": false,
  "unit": null
 },
 {
  "key": "stop_price",
  "title": "止损价",
  "text": "持仓计划里的止损价：你还没写。跌破就会提醒你，不受你的规则和设置影响。这条是硬保证，不能关。",
  "enabled": true,
  "levels": null,
  "editable": false,
  "hard_guarantee": true,
  "applies_to": "写了计划价位的持仓",
  "yields_on": [],
  "changed": false,
  "threshold_editable": false,
  "unit": null
 },
 {
  "key": "filings",
  "title": "新公告（SEC 申报）",
  "text": "新公告（SEC 申报）：盯你的持仓和研究队列。这条是硬保证，不能关。",
  "enabled": true,
  "levels": null,
  "editable": false,
  "hard_guarantee": true,
  "applies_to": "持仓和研究队列",
  "yields_on": [],
  "changed": false,
  "threshold_editable": false,
  "unit": null
 }
];

const THRESHOLDS = {"quiet": {"remind": 2.5, "major": 5.0}, "standard": {"remind": 2.0, "major": 4.0}, "sensitive": {"remind": 1.5, "major": 3.0}};
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
  if (!row) return { status: 400, detail: { error_code: "refused_1", reason: "没有这条系统默认。" } };
  if (row.hard_guarantee) return { status: 400, detail: { error_code: "refused_2", reason: "这条是硬保证，不能关。" } };
  if (!row.editable) return { status: 400, detail: { error_code: "refused_3", reason: "这条默认不在这里调整。" } };
  if (typeof body?.enabled === "boolean") row.enabled = body.enabled;
  if (Array.isArray(body?.levels)) {
    if (body.levels.some((l) => !(Number(l.threshold) > 0)) && !["new_high_52w", "new_low_52w"].includes(key)) return { status: 400, detail: { error_code: "refused_4", reason: "门槛要大于 0。" } };
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
  if (!row || !base) return { status: 400, detail: { error_code: "refused_5", reason: "没有这条系统默认。" } };
  if (row.hard_guarantee) return { status: 400, detail: { error_code: "refused_6", reason: "这条是硬保证，不能关。" } };
  Object.assign(row, { enabled: true, changed: false, levels: structuredClone(base.levels), text: DEFAULT_LEVELS[key] && TEXTS[key] ? TEXTS[key](DEFAULT_LEVELS[key]) : base.text });
  return { row };
}
