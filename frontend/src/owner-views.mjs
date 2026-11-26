// 你的看法 (the owner's view of a company): pure helpers for the company page card and the memory page section.  The backend's rows are
// { id, symbol, text, quote, status: active|superseded|dropped, created_at, ended_at }.

const STATUS_PHRASES = { superseded: "已更新", dropped: "已撤回", archived: "已归档" };

/** The phrase naming an earlier version's status (已更新 / 已撤回 / 已归档); "" for the active one or an unknown status. */
export function statusPhrase(status) { return STATUS_PHRASES[status] ?? ""; }

/** The month and day of an instant as the owner lives it (Beijing), or null when it is not a date. */
export function monthDay(value, timeZone = "Asia/Shanghai") {
  const date = new Date(value ?? "");
  if (Number.isNaN(date.valueOf())) return null;
  const parts = new Intl.DateTimeFormat("en-US", { month: "numeric", day: "numeric", timeZone }).formatToParts(date);
  return { month: Number(parts.find(p => p.type === "month")?.value), day: Number(parts.find(p => p.type === "day")?.value) };
}

/** `M月D日` (zh-CN) or `M/D` (en-US) of an instant; "" when it is not a date. */
export function dayLabel(value, locale = "zh-CN") {
  const md = monthDay(value);
  if (!md) return "";
  return locale === "en-US" ? `${md.month}/${md.day}` : `${md.month}月${md.day}日`;
}

/** The versions as the card shows them: the active one (or null) and the earlier ones newest first (the backend sends newest first; this does not trust it). */
export function splitVersions(versions) {
  const list = Array.isArray(versions) ? versions.filter(v => v && typeof v === "object") : [];
  const byNewest = [...list].sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
  const active = byNewest.find(v => v.status === "active") ?? null;
  return { active, earlier: byNewest.filter(v => v !== active) };
}

/** The archived view the card shows as its current one: there is no active view and the newest version was archived (a view the quarterly settle set aside).  Else null. */
export function archivedCurrent(versions) {
  const { active, earlier } = splitVersions(versions);
  return !active && earlier[0]?.status === "archived" ? earlier[0] : null;
}

/** True when the card has anything to say: a view or any history.  No view and no history means no card at all. */
export function hasAnyView(versions) {
  const { active, earlier } = splitVersions(versions);
  return Boolean(active) || earlier.length > 0;
}

/** The dates of an earlier version: `M月D日 – M月D日` (said, then ended); just the first when there is no end date. */
export function versionSpan(version, locale = "zh-CN") {
  const from = dayLabel(version?.created_at, locale), to = dayLabel(version?.ended_at, locale);
  return from && to ? `${from} – ${to}` : from || to;
}

// 回头看 (the quarterly look back at a view).  The review text is the model's and is never altered here; only the code-built basis line and the figure caution are made.
const VERDICTS = { held: ["成立", "success"], not_held: ["没有成立", "failure"], mixed: ["部分成立", "neutral"], too_early: ["还早", "neutral"], unclear: ["说不准", "neutral"] };

/** The review a version carries, or null when it has none or it is empty. */
export function reviewOf(version) {
  const review = version?.review;
  return review && typeof review === "object" && String(review.text ?? "").trim() ? review : null;
}

/** The badge of a verdict: `{ label, kind }`.  An unknown verdict falls back to the server's own label, as neutral. */
export function verdictBadge(review) {
  const known = VERDICTS[review?.verdict];
  if (known) return { label: known[0], kind: known[1] };
  return { label: String(review?.verdict_label ?? ""), kind: "neutral" };
}

const price = value => (typeof value === "number" && Number.isFinite(value) ? `$${value.toFixed(2)}` : "");

/** `+12.3%` / `-4.0%` of a number; "" when it is not one. */
export function changeLabel(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return `${value >= 0 ? "+" : "-"}${Math.abs(value).toFixed(1)}%`;
}

/**
 * The basis line from the code's own snapshot: `说的时候 $X → 现在 $Y（+Z%） · 最新一季 FYxx Qx`.  A part with no data is left out, never made up; "" when nothing is left.
 * `words` carries the translated 说的时候 / 现在 / 最新一季 (default Chinese).
 */
export function basisLine(basis, words = {}) {
  const w = { then: "说的时候", now: "现在", quarter: "最新一季", ...words };
  const then = price(basis?.price_then?.close), now = price(basis?.price_now?.close), change = changeLabel(basis?.change_pct);
  const parts = [];
  if (then && now) parts.push(`${w.then} ${then} → ${w.now} ${now}${change ? `（${change}）` : ""}`);
  else if (now) parts.push(`${w.now} ${now}`);
  else if (then) parts.push(`${w.then} ${then}`);
  const quarter = String(basis?.quarter_label ?? "").trim();
  if (quarter) parts.push(`${w.quarter} ${quarter}`);
  return parts.join(" · ");
}

/** The figures of the review the system could not find in the data it gave the model (as written); [] when there are none. */
export function strayFigures(review) {
  return Array.isArray(review?.unmatched_figures) ? review.unmatched_figures.map(x => String(x).trim()).filter(Boolean) : [];
}
