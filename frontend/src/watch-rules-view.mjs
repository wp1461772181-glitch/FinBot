// 它在帮你盯的 → 规则 (stage 5b-2): pure helpers for the rules block of the memory page (GET /agent-chat/watch).  The server writes every rule's and every default's reading (`text`, `title`);
// nothing here rewrites those.  This file words the few things the page itself says: a rule's status, the sigma numbers of a sensitivity, a threshold as typed, what a refused write says.
// Words that carry a number are made for the locale here; fixed words go through the page's own t().

const isObject = (value) => Boolean(value) && typeof value === "object";
const finite = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** The three sensitivities in the order the control shows them: [value, the Chinese label the page translates]. */
export const SENSITIVITIES = [["quiet", "安静"], ["standard", "标准"], ["sensitive", "灵敏"]];

/** Plain number text: 25, 2.5, 0.5 (no trailing zeros, no exponent); "" when it is not a number. */
export function plainNum(value) {
  const n = finite(typeof value === "string" && value.trim() !== "" ? Number(value) : value);
  return n === null ? "" : String(Number(n.toFixed(4)));
}

/**
 * A rule's status as `{ kind, label, active }` (`label` is a Chinese key the page translates).  The server may send the code (active, expired, done) or its own words (「已过期（不再检查）」,
 * 「已完成…」); anything else, and nothing, is 生效.  `kind` is the StatusBadge kind: only a finished rule reads as done, the others are neutral.
 */
export function ruleStatus(raw) {
  const text = String(raw ?? "").trim();
  if (text === "expired" || text.startsWith("已过期")) return { kind: "neutral", label: "已过期", active: false };
  if (text === "done" || text.startsWith("已完成")) return { kind: "success", label: "已完成", active: false };
  return { kind: "neutral", label: "生效", active: true };
}

/** The low/high sigma pair of one sensitivity: `[2, 4]`, or an object (`{ low, high }`, else its first two numbers in order); null when it is neither. */
export function sigmaPair(value) {
  const numbers = Array.isArray(value) ? value : isObject(value) ? ("low" in value && "high" in value ? [value.low, value.high] : Object.values(value)) : [];
  const [low, high] = numbers.map(finite);
  return low !== null && low !== undefined && high !== null && high !== undefined ? [low, high] : null;
}

/** 「约 2σ 值得提醒，4σ 算重大」 / "about 2σ is worth a heads-up, 4σ is major"; "" when the server sent no numbers.  σ is a day's move measured in that stock's own usual daily swing. */
export function sigmaWords(value, locale = "zh-CN") {
  const pair = sigmaPair(value);
  if (!pair) return "";
  const [low, high] = pair.map(plainNum);
  return locale === "en-US" ? `about ${low}σ is worth a heads-up, ${high}σ is major` : `约 ${low}σ 值得提醒，${high}σ 算重大`;
}

/** The settings as the page reads them: `{ sensitivity, shortMoves, choices: [{ value, label, words }] }`; an unknown sensitivity is 标准. */
export function settingsView(settings, locale = "zh-CN") {
  const s = isObject(settings) ? settings : {};
  const thresholds = isObject(s.thresholds) ? s.thresholds : {};
  const known = SENSITIVITIES.some(([value]) => value === s.sensitivity);
  return {
    sensitivity: known ? s.sensitivity : "standard", shortMoves: s.short_moves === true,
    choices: SENSITIVITIES.map(([value, label]) => ({ value, label, words: sigmaWords(thresholds[value], locale) })),
  };
}

const LEVEL_LABELS = { remind: "提醒", urgent: "加急" };
// The unit of each editable default's threshold; a default with no unit here has no threshold to edit (52-week high and low).
const UNITS = { concentration: "%", portfolio_drawdown: "%", down_streak: "days", volume_surge: "x" };

/** Unit of a threshold as the page words it: "%", "x" (times) or "days"; "" when this default has no threshold. */
export function thresholdUnit(key) { return UNITS[key] ?? ""; }

/**
 * The defaults of the page.  Each: `{ key, title, text, enabled, hard, editable, levels: [{ level, label, threshold, text }] | null, unit, canEdit, canReset, yields, applies }`.
 * `canEdit`: it can be edited and has a threshold.  `canReset`: 恢复默认 is offered, when the server says it was changed; a server that does not say (no `changed`) gets it on every editable
 * default, so a change can always be undone.  A hard guarantee (the stop price, filings) is never editable and never resettable.
 */
export function presetRows(presets) {
  return (Array.isArray(presets) ? presets : []).filter(isObject).map((preset) => {
    const key = String(preset.key ?? "");
    const hard = preset.hard_guarantee === true;
    const editable = preset.editable === true && !hard;
    const levels = Array.isArray(preset.levels) ? preset.levels.filter(isObject).map((l) => ({ level: String(l.level ?? ""), label: LEVEL_LABELS[l.level] ?? String(l.level ?? ""), threshold: finite(Number(l.threshold)) ?? 0, text: plainNum(Number(l.threshold)) })) : null;
    const yields = (Array.isArray(preset.yields_on) ? preset.yields_on : []).map(String).filter(Boolean);
    const applies = Array.isArray(preset.applies_to) ? preset.applies_to.map(String).filter(Boolean) : typeof preset.applies_to === "string" ? preset.applies_to.trim() : "";
    const changed = typeof preset.changed === "boolean" ? preset.changed : typeof preset.overridden === "boolean" ? preset.overridden : null;
    return {
      key, title: String(preset.title ?? key), text: String(preset.text ?? "").trim(), enabled: preset.enabled !== false, hard, editable,
      levels, unit: thresholdUnit(key), canEdit: editable && levels !== null && levels.length > 0 && thresholdUnit(key) !== "",
      canReset: !hard && editable && changed !== false, yields, applies,
    };
  });
}

/** 「对 INTC 让位给你的规则」 / "Yields to your rule on INTC"; "" when no symbol. */
export function yieldsLine(symbols, locale = "zh-CN") {
  const list = Array.isArray(symbols) ? symbols.filter(Boolean) : [];
  if (list.length === 0) return "";
  return locale === "en-US" ? `Yields to your rule on ${list.join(", ")}` : `对 ${list.join("、")} 让位给你的规则`;
}

/** What a default applies to: the symbols joined in the locale's way, or the server's sentence as it is; "" when nothing. */
export function appliesText(applies, locale = "zh-CN") {
  if (Array.isArray(applies)) return applies.length ? applies.join(locale === "en-US" ? ", " : "、") : "";
  return typeof applies === "string" ? applies : "";
}

/**
 * The owner's rules of the page: `{ id, symbol, text, status: { kind, label, active }, fired, lastFired, override }`.  `fired` says the server sent `last_fired` at all (its sentence, e.g. 「近 7 天没有触发」,
 * is `lastFired`; an empty one with `fired` true is 「还没触发过」).  `override` is the server's note of the default it takes the place of, or true for a plain one, or "".
 */
export function ruleRows(rules) {
  return (Array.isArray(rules) ? rules : []).filter(isObject).map((rule) => ({
    id: String(rule.id ?? ""), symbol: String(rule.symbol ?? ""), text: String(rule.text ?? "").trim(), status: ruleStatus(rule.status),
    fired: "last_fired" in rule, lastFired: String(rule.last_fired ?? "").trim(),
    override: typeof rule.overrides_default === "string" ? rule.overrides_default.trim() : rule.overrides_default === true ? true : "",
  }));
}

/**
 * Check a threshold edit before it is sent: `inputs` are the typed strings, one per level.  `{ levels }` ready to send, or `{ error }` (a Chinese key the page translates).
 * A threshold is a number above 0; a share cannot pass 100; a streak is a whole number of days, at least 2; with two levels the urgent one is the larger.  The server checks again and its reason wins.
 */
export function checkThresholds(key, levels, inputs) {
  const unit = thresholdUnit(key);
  const out = [];
  for (let i = 0; i < levels.length; i += 1) {
    const raw = String(inputs[i] ?? "").trim().replace(/,/g, ".");
    const n = raw === "" ? NaN : Number(raw);
    if (!Number.isFinite(n) || n <= 0) return { error: "请填一个大于 0 的数。" };
    if (unit === "%" && n > 100) return { error: "百分比不能超过 100。" };
    if (unit === "days" && (!Number.isInteger(n) || n < 2)) return { error: "天数要是不小于 2 的整数。" };
    out.push({ threshold: n, level: levels[i].level });
  }
  if (out.length === 2 && out[0].level === "remind" && out[1].level === "urgent" && out[1].threshold <= out[0].threshold) return { error: "加急的门槛要比提醒的大。" };
  return { levels: out };
}

/** The reason to show for a refused write: `detail.reason` (the server's `{ error_code, reason }`), else a Chinese string `detail`, else a plain line for the status. */
export function watchWriteError(status, detail) {
  const reason = isObject(detail) && typeof detail.reason === "string" ? detail.reason.trim() : "";
  if (reason) return reason;
  if (typeof detail === "string" && /[一-鿿]/.test(detail)) return detail;
  if (status === 403 || status === 401) return "登录个人聊天后才能修改。";
  if (status === 404) return "这条已不存在。";
  return "保存失败，请重试。";
}
