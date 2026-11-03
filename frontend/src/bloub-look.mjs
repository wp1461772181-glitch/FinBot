// Bot avatar look for the bloub engine (src/bloub): which silhouette + colour a bot gets, and which engine state it shows.
// Pure functions (no engine import) so node --test can cover them.
import { DEFAULT_AVATAR, parseAvatar } from "./orb.mjs";

// The full bloub customisation catalog (jeremy-prt/bloub @ b4bb3c1, the ids of src/bloub/skins.ts, expressions.ts, states.ts).
// bloub-look.test.mjs parses the vendored sources and fails if these lists drift from them.
export const BLOUB_SHAPES = ["cercle", "galet", "squircle", "capsule", "triangle", "hexagone", "nuage", "goutte"];
export const BLOUB_COLORS = ["encre", "brun", "rouge", "orange", "ambre", "vert", "turquoise", "bleu", "violet", "rose", "gris", "creme"];
export const BLOUB_EXPRESSIONS = ["neutre", "attentif", "surpris", "excite", "heureux", "hilare", "colere", "triste", "effraye",
  "mefiant", "confus", "curieux", "fier", "timide", "blase", "somnolent"];
/** The 14 animation states of the catalog, plus the UI-only `swirl` transition. */
export const BLOUB_STATES = ["idle", "thinking", "wink", "wide", "alert", "notify", "exclaim", "sleep", "egg", "hexagon", "play",
  "orbit", "burst", "comet", "swirl"];
/** The one resting face of every bot (the catalogue's neutral/calm). Expressions are not customisable: work phases drive them (bloub-mood). */
export const CALM_EXPRESSION = "neutre";
export const DEFAULT_LOOK = { shape: "cercle", color: "encre" };
const FIELDS = { shape: BLOUB_SHAPES, color: BLOUB_COLORS };

// A face the user picked in the older editor (silhouette × eye colour) maps to a fixed look; kept for bots that never got a stored look.
const STYLE_SHAPE = { kline: "cercle", pure: "galet", bull: "goutte", square: "squircle" };
const MOOD_COLOR = { idle: "vert", focus: "bleu", bull: "ambre", mono: "encre" };

/** The fixed look of a silhouette × colour pick (older editor swatches). */
export function faceLook(style, mood) { return { shape: STYLE_SHAPE[style], color: MOOD_COLOR[mood] }; }

/** FNV-1a, 32-bit, non-negative. */
export function hashString(value) {
  let h = 0x811c9dc5;
  for (const ch of String(value)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
  return h >>> 0;
}

/** The default look of a bot that was never customised: shape and colour hashed from its id out of the full catalog, calm face. */
export function defaultLook(id) {
  const h = hashString(id || "finbot");
  return { shape: BLOUB_SHAPES[h % BLOUB_SHAPES.length], color: BLOUB_COLORS[Math.floor(h / BLOUB_SHAPES.length) % BLOUB_COLORS.length] };
}

/** A valid {shape, color} copy, or null for anything else (missing, partial, unknown ids). A stored `expression` (older looks) is ignored. */
export function normalizeLook(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  for (const [field, list] of Object.entries(FIELDS)) if (!list.includes(raw[field])) return null;
  return { shape: raw.shape, color: raw.color };
}

export function sameLook(a, b) { return Boolean(a && b) && a.shape === b.shape && a.color === b.color; }

/** What a bot shows as its base: the stored look; else an explicit older face pick; else the hashed default. A broken stored value falls through. */
export function resolveLook(id, avatar, stored) {
  const own = normalizeLook(stored);
  if (own) return own;
  const value = String(avatar ?? "").trim();
  const parsed = parseAvatar(value);
  if (parsed.kind === "bot" && /^bot:/.test(value) && value !== DEFAULT_AVATAR) return { ...faceLook(parsed.style, parsed.mood) };
  return defaultLook(id);
}

/** {shape, color} of {@link resolveLook} without a stored look (older call sites and tests). */
export function bloubLook(id, avatar) { const { shape, color } = resolveLook(id, avatar, null); return { shape, color }; }

/** Selector state: a copy of `look` with shape or colour changed. An unknown field or id returns `look` itself. */
export function pickLook(look, field, id) {
  const list = FIELDS[field];
  return list && list.includes(id) ? { ...look, [field]: id } : look;
}

/** What to send on save: `picked` is the look the user clicked to (null: they never touched the selector). Any click counts as a
 * choice, including one that lands on the default combination; undefined = send nothing (untouched, or already what is stored). */
export function lookForSave(picked, stored) {
  const look = normalizeLook(picked);
  return look && !sameLook(look, normalizeLook(stored)) ? look : undefined;
}

/** A starting look for a bot being created: any shape and colour of the catalog, calm face. */
export function randomLook(random = Math.random) {
  const at = list => list[Math.min(list.length - 1, Math.floor(random() * list.length))];
  return { shape: at(BLOUB_SHAPES), color: at(BLOUB_COLORS) };
}

/** Engine state: orbit while a turn is running, notify when there is something unread, otherwise idle. */
export function bloubState({ running = false, unread = false } = {}) {
  return running ? "orbit" : unread ? "notify" : "idle";
}
