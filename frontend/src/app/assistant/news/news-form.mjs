// The news-source form as plain data (P8.1): what the new drawer shows, how an ID is made from a name, which rules stop a save, and the request body it makes.
// The body is the old form's key for key (PersonalPages.tsx before P8.1): id, name, kind, url, homepage (only when filled), language, markets, tags, alternates, rea_repair, enabled.

/** The old rule for an ID, and its sentence. */
export const ID_PATTERN = /^[A-Za-z0-9._-]{2,80}$/;
export const URL_PATTERN = /^https?:\/\/.+/i;
export const MAX_ID = 80;
export const MAX_NAME = 120;
export const KINDS = ["rss", "http_json", "http_html"];
export const KIND_LABELS = { rss: "RSS / Atom 订阅源", http_json: "HTTP JSON 接口", http_html: "HTTP HTML 列表页" };
export const KIND_SHORT = { rss: "RSS / Atom", http_json: "HTTP JSON", http_html: "HTTP HTML" };
export const HEALTH_LABELS = { ok: "健康", degraded: "降级", failed: "异常" };
export const MESSAGES = {
  id: "请填写有效的新闻源 ID（2-80 位字母、数字、连字符或下划线，如 cls-telegraph）。",
  idTaken: "已经有这个 ID 的新闻源了，请换一个（保存同一个 ID 会覆盖它）。",
  idEmpty: "名称里取不出可用的字母或数字，请自己填一个 ID。",
  url: "抓取地址须以 http:// 或 https:// 开头。",
};

/** An ID made from a name: the ASCII letters and digits in lower case, every other run of characters one "-", no "-" at either end, at most 80 long.  "" when fewer than 2 are left. */
export function slugFromName(name) {
  const slug = String(name ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, MAX_ID).replace(/-+$/g, "");
  return slug.length >= 2 ? slug : "";
}

/** The generated ID for a name among the IDs that exist: the slug, or the slug with -2, -3 ... when it is taken.  "" when the name gives none. */
export function generateId(name, existing = []) {
  const base = slugFromName(name);
  if (!base) return "";
  const taken = new Set(existing);
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const suffix = `-${n}`;
    const candidate = `${base.slice(0, MAX_ID - suffix.length).replace(/-+$/g, "")}${suffix}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** The form as a new source opens it (the old openForm()): RSS, market US, tag news, both switches on.  `idTouched` is true once the reader has typed in the ID box (the name then stops filling it). */
export function blankDraft() {
  return { id: "", idTouched: false, name: "", kind: "rss", url: "", homepage: "", language: "zh-CN", markets: ["US"], tags: ["news"], alternates: [], reaRepair: true, enabled: true };
}

/** The form as an existing source opens it (what the old form showed): the ID is its own and does not change. */
export function draftFromSource(source) {
  return {
    id: source.id, idTouched: true, name: source.name ?? "", kind: source.kind ?? "rss", url: source.url ?? "", homepage: source.homepage ?? "", language: source.language ?? "zh-CN",
    markets: [...(source.markets ?? ["US"])], tags: [...(source.tags ?? ["news"])], alternates: [...(source.alternates ?? [])], reaRepair: source.rea_repair ?? true, enabled: source.enabled ?? true,
  };
}

/** The draft after the name changed: while the reader has not touched the ID of a new source, the ID follows the name. */
export function withName(draft, name, existing = []) {
  return draft.idTouched ? { ...draft, name } : { ...draft, name, id: generateId(name, existing) };
}

/** What a tag box does to what is typed in each of the three lists (the old form's split-and-clean, item by item). */
export const normalizeMarket = (raw) => String(raw).trim().toUpperCase();
export const normalizeTag = (raw) => String(raw).trim();

/** The rules that stop a save, each with its field and the old sentence (the first two) or the new one for a taken ID. `existing` is the IDs of the other sources; `editing` is true for an existing source. */
export function validateDraft(draft, { editing = false, existing = [] } = {}) {
  const problems = [];
  const id = String(draft.id ?? "").trim();
  if (!ID_PATTERN.test(id)) problems.push({ field: "id", message: !id && !editing && String(draft.name ?? "").trim() && !draft.idTouched ? MESSAGES.idEmpty : MESSAGES.id });
  else if (!editing && existing.includes(id)) problems.push({ field: "id", message: MESSAGES.idTaken });
  if (!URL_PATTERN.test(String(draft.url ?? "").trim())) problems.push({ field: "url", message: MESSAGES.url });
  return problems;
}

const clean = (list, normalize) => (list ?? []).map((item) => normalize(item)).filter(Boolean);

/** The request body of a save: the old form's, key for key. */
export function inputFromDraft(draft) {
  const id = String(draft.id).trim();
  const homepage = String(draft.homepage ?? "").trim();
  return {
    id,
    name: String(draft.name ?? "").trim() || id,
    kind: draft.kind,
    url: String(draft.url).trim(),
    ...(homepage ? { homepage } : {}),
    language: String(draft.language ?? "").trim() || "zh-CN",
    markets: clean(draft.markets, normalizeMarket),
    tags: clean(draft.tags, normalizeTag),
    alternates: clean(draft.alternates, normalizeTag),
    rea_repair: Boolean(draft.reaRepair),
    enabled: Boolean(draft.enabled),
  };
}

/** The words for a test fetch (what the old row showed): success with the counts and up to two samples, or the reason it did not pass (reason, else the code, else none). */
export function dryRunView(result) {
  if (result.ok) return { ok: true, raw: result.raw_count ?? 0, valid: result.valid_count ?? 0, samples: (result.sample ?? []).slice(0, 2).map((item) => ({ title: item.title, url: item.url, at: String(item.published_at ?? "").slice(0, 16) })) };
  return { ok: false, reason: result.reason || result.error_code || "" };
}

/** The sentence for a repair: success counts the sample, a refusal says the code the server gave, else that no spare source was found.  Both as `{ kind, count?, reason? }`; the page writes the words. */
export function repairView(result) {
  return result.ok ? { ok: true, count: result.sample?.length ?? 0 } : { ok: false, reason: result.error_code ?? "" };
}

/** The health of a source: one of the three the server knows, or whatever else it said (shown as it is). */
export function healthKind(health) { return health === "ok" || health === "degraded" || health === "failed" ? health : "other"; }
