// A bot's animation personality (design 6.4 / 6.5): archetype, tempo, easing, resting gaze, aura variant.
// Pure (no DOM, no engine): node --test covers it.  The five bots that exist today are pinned by id (then by name); every other
// bot is derived from its record by the rules of 6.4.  A browser-local override (D4) sits on top of both.
import { hashString } from "./bloub-look.mjs";
import { PERSONA_PRESETS, presetFor, presetLook } from "./bot-persona-presets.mjs";

export const ARCHETYPES = ["lead", "tracker", "sentinel", "reader", "generalist"];
export const EASINGS = ["smooth", "spring", "step"];
export const REST_GAZES = ["follow", "ahead-right", "scan", "down", "front"];
/** Aura families (3 variants each, drawn by src/aura: see aura/index.mjs for the variant -> file table).  Tracker's three are fixed by 6.4/6.5. */
export const AURA_VARIANTS = {
  lead: ["ticks", "gauge", "pips"],
  tracker: ["speed-lines", "halo", "reticle"],
  sentinel: ["ticker", "morse", "beacon"],
  reader: ["page-lines", "margin-ticks", "underline"],
  generalist: ["orbit-dots", "twin-dots", "trio"]
};
export const TEMPO_MIN = 0.8;
export const TEMPO_MAX = 1.25;
/** Annualised volatility thresholds of 6.4 (fractions): above HIGH = fast, below LOW = calm, between = standard. */
export const VOL_HIGH = 0.45;
export const VOL_LOW = 0.25;

/** What each archetype may be when nothing else decides (a hash of the bot id picks within it). `gaze` is the resting gaze. */
const RANGES = {
  lead: { tempo: [0.95, 1, 1.05], easing: ["smooth"], gaze: "follow" },
  tracker: { gaze: "follow" }, // tracker picks one of the three volatility bands (BANDS) instead
  sentinel: { tempo: [1, 1.1, 1.2], easing: ["step"], gaze: "scan" },
  reader: { tempo: [0.8, 0.85, 0.9], easing: ["smooth"], gaze: "down" },
  generalist: { tempo: [0.9, 1, 1.1], easing: ["smooth"], gaze: "follow" }
};
/** The tracker's three characters (6.4): where volatility lands, or where the id hash lands without market data. */
const BANDS = {
  fast: { tempo: 1.25, easing: "spring", auraVariant: "speed-lines", restGaze: "ahead-right" },
  standard: { tempo: 1, easing: "smooth", auraVariant: "reticle", restGaze: "follow" },
  calm: { tempo: 0.9, easing: "smooth", auraVariant: "halo", restGaze: "front" }
};
const BAND_ORDER = ["calm", "standard", "fast"];

export { PERSONA_PRESETS, presetFor, presetLook };

/** The symbol a tracker bot watches: its default company, else its first focus company (the same order as workspace-cards.botSymbol). */
export function trackedSymbol(bot) {
  const symbol = bot?.default_company?.symbol ?? bot?.focus?.companies?.[0]?.symbol;
  return typeof symbol === "string" && symbol.trim() ? symbol.trim().toUpperCase() : null;
}

/** 6.4 rules in order, first hit wins. */
export function archetypeOf(bot) {
  if (bot?.is_default) return "lead";
  if (bot?.template === "news_monitor") return "sentinel";
  if (bot?.template === "earnings_reader") return "reader";
  if (bot?.default_company?.symbol || bot?.template === "company_researcher") return "tracker";
  return "generalist";
}

/** Which of the three bands an annualised volatility (a fraction, 0.45 = 45%) falls in; null for anything that is not a number. */
export function volatilityBand(volatility) {
  if (typeof volatility !== "number" || !Number.isFinite(volatility) || volatility < 0) return null;
  return volatility > VOL_HIGH ? "fast" : volatility < VOL_LOW ? "calm" : "standard";
}

const pick = (list, h) => list[h % list.length];

function derived(bot, archetype, volatility) {
  const h = hashString(bot?.id || bot?.name || "bot");
  const variants = AURA_VARIANTS[archetype];
  if (archetype === "tracker") {
    const band = (trackedSymbol(bot) ? volatilityBand(volatility) : null) ?? pick(BAND_ORDER, h);
    return { archetype, ...BANDS[band] };
  }
  const range = RANGES[archetype];
  return { archetype, tempo: pick(range.tempo, h), easing: pick(range.easing, Math.floor(h / 7)), restGaze: range.gaze, auraVariant: pick(variants, Math.floor(h / 13)) };
}

/** The knobs a stored override may hold, each checked; anything else is dropped. */
export function cleanOverrides(raw) {
  const out = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  if (ARCHETYPES.includes(raw.archetype)) out.archetype = raw.archetype;
  if (typeof raw.tempo === "number" && Number.isFinite(raw.tempo) && raw.tempo >= TEMPO_MIN && raw.tempo <= TEMPO_MAX) out.tempo = raw.tempo;
  if (EASINGS.includes(raw.easing)) out.easing = raw.easing;
  return out;
}

/**
 * The personality of a bot: `{ archetype, tempo, easing, restGaze, auraVariant, source }`.
 * `bot` is the record ({ id, name, template, is_default, default_company, focus }); `volatility` is the tracked stock's stored
 * annualised volatility (a fraction) when there is one; `overrides` is what readOverrides gave.  source: "preset" (pinned),
 * "derived" (rules + id hash) or "override" (the reader changed something).
 */
export function derivePersona(bot, { volatility, overrides } = {}) {
  const preset = presetFor(bot);
  let persona = preset
    ? { archetype: preset.archetype, tempo: preset.tempo, easing: preset.easing, restGaze: preset.restGaze, auraVariant: preset.auraVariant, source: "preset" }
    : { ...derived(bot, archetypeOf(bot), volatility), source: "derived" };
  const own = cleanOverrides(overrides);
  if (Object.keys(own).length === 0) return persona;
  // A new archetype brings its own gaze and aura (derived from this bot's id); tempo and easing overrides then sit on top.
  if (own.archetype && own.archetype !== persona.archetype) persona = { ...derived(bot, own.archetype, volatility), source: "override" };
  return { ...persona, ...(own.tempo !== undefined ? { tempo: own.tempo } : {}), ...(own.easing ? { easing: own.easing } : {}), source: "override" };
}

// --- browser-local storage (D4: not synced) -----------------------------------------------------------------------------------

const OVERRIDE_KEY = "market-evidence-agent:bot-persona:v1:";
const VOLATILITY_KEY = "market-evidence-agent:bot-volatility:v1:";

function readJson(storage, key) {
  try { const raw = storage?.getItem(key); return raw ? JSON.parse(raw) : null; } catch { return null; }
}

/** A bot's saved overrides ({} when none or unreadable; bad fields dropped). */
export function readOverrides(storage, botId) {
  return botId ? cleanOverrides(readJson(storage, OVERRIDE_KEY + botId)) : {};
}

/** Save overrides (only the valid fields; none left removes the entry).  Returns what was stored. */
export function writeOverrides(storage, botId, overrides) {
  const clean = cleanOverrides(overrides);
  if (!botId) return clean;
  try {
    if (Object.keys(clean).length) storage?.setItem(OVERRIDE_KEY + botId, JSON.stringify(clean));
    else storage?.removeItem(OVERRIDE_KEY + botId);
  } catch { /* the choice still applies to this visit through the caller */ }
  return clean;
}

export function clearOverrides(storage, botId) { return writeOverrides(storage, botId, {}); }

// --- volatility (a tracker's character, computed once and then kept) -----------------------------------------------------------

/** Trading days of returns that count (design 6.4: the last 60). */
export const VOL_WINDOW = 60;
const TRADING_DAYS = 252;
const MIN_RETURNS = 20;

/** Annualised volatility (fraction): sample standard deviation of the last 60 daily returns x sqrt(252).  null with fewer than 20 usable returns. */
export function annualizedVolatility(closes) {
  const rows = (Array.isArray(closes) ? closes : []).filter(value => typeof value === "number" && Number.isFinite(value) && value > 0).slice(-(VOL_WINDOW + 1));
  const returns = [];
  for (let i = 1; i < rows.length; i++) returns.push(rows[i] / rows[i - 1] - 1);
  if (returns.length < MIN_RETURNS) return null;
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const variance = returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length - 1);
  return Math.sqrt(variance) * Math.sqrt(TRADING_DAYS);
}

/** The volatility stored for this bot, if it was computed for the same symbol; null otherwise (symbol changed = a new first time). */
export function readVolatility(storage, botId, symbol) {
  const stored = botId ? readJson(storage, VOLATILITY_KEY + botId) : null;
  return stored && stored.symbol === symbol && typeof stored.value === "number" && Number.isFinite(stored.value) && stored.value >= 0 ? stored.value : null;
}

export function writeVolatility(storage, botId, symbol, value) {
  if (!botId || !symbol || typeof value !== "number" || !Number.isFinite(value) || value < 0) return false;
  try { storage?.setItem(VOLATILITY_KEY + botId, JSON.stringify({ symbol, value })); return true; } catch { return false; }
}
