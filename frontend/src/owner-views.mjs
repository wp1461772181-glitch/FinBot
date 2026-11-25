// 你的看法 (the owner's view of a company): pure helpers for the company page card and the memory page section.  The backend's rows are
// { id, symbol, text, quote, status: active|superseded|dropped, created_at, ended_at }.

const STATUS_PHRASES = { superseded: "已更新", dropped: "已撤回" };

/** The phrase naming an earlier version's status (已更新 / 已撤回); "" for the active one or an unknown status. */
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
