// The evidence page's pure parts: how a version's research brief is cut into the events one material supports, and the small labels around them.
// Phrases are zh-CN keys; the components translate them.

/** The groups an event can sit in, in the order the drawer shows them (design 4.7). */
export const EVENT_GROUPS = [
  { key: "supporting", phrase: "潜在利好", tone: "positive" },
  { key: "counter", phrase: "潜在利空 / 反证", tone: "negative" },
  { key: "facts", phrase: "新增事实", tone: "fact" },
  { key: "background", phrase: "持续背景", tone: "background" },
  { key: "conflicts", phrase: "来源冲突", tone: "uncertain" },
  { key: "unknowns", phrase: "不确定项", tone: "uncertain" },
  { key: "changes", phrase: "版本变化", tone: "fact" },
];

const CHANGE_PHRASE = { added: "新增", withdrawn: "撤回", modified: "修订", source_status_changed: "来源状态变化" };
export const changePhrase = (value) => CHANGE_PHRASE[value] ?? value;

const SECTION_PHRASE = { facts: "事实", supporting: "利好", counter: "利空", uncertainties: "不确定项" };
export const sectionPhrase = (section) => SECTION_PHRASE[section] ?? section;

/**
 * The events of one brief that rest on one analysis: every statement of every group keeps only the citations that point into that analysis,
 * and a statement with none left is not that material's event.  `t` translates a phrase; `locale` picks the punctuation of the two composed lines.
 * Returns [{ key, label, tone, rows: [{ text, citations }] }] with the groups that have rows.
 */
export function eventGroups(brief, analysisId, t, locale) {
  const en = locale === "en-US";
  const rowsOf = {
    supporting: brief.supporting.map((row) => ({ text: row.statement, citations: row.citations })),
    counter: brief.counter.map((row) => ({ text: row.statement, citations: row.citations })),
    facts: brief.new_facts.map((row) => ({ text: row.statement, citations: row.citations })),
    background: brief.background.map((row) => ({ text: en ? `${row.statement} (Continuing reason: ${row.continuing_reason})` : `${row.statement}（持续原因：${row.continuing_reason}）`, citations: row.citations })),
    conflicts: brief.conflicts.map((row) => ({ text: row.description, citations: row.citations })),
    unknowns: brief.unknowns.map((row) => ({ text: en ? `${row.question}: ${row.reason}` : `${row.question}：${row.reason}`, citations: row.citations })),
    changes: brief.changes.map((row) => ({ text: `${t(changePhrase(row.change_type))}: ${row.description}`, citations: row.citations })),
  };
  return EVENT_GROUPS.flatMap((group) => {
    const rows = rowsOf[group.key].flatMap((row) => {
      const citations = row.citations.filter((citation) => citation.analysis_id === analysisId);
      return citations.length ? [{ ...row, citations }] : [];
    });
    return rows.length ? [{ key: group.key, label: t(group.phrase), tone: group.tone, rows }] : [];
  });
}

/** How many events a material has in a version (the card's 「N 条关联判断」). */
export const eventCount = (groups) => groups.reduce((count, group) => count + group.rows.length, 0);

export const SOURCE_LABEL = { official_filing: { zh: "SEC 官方文件", en: "SEC filing" }, uploaded_media: { zh: "上传媒体材料", en: "Uploaded media" } };
export const sourceTypeLabel = (sourceType, locale) => (SOURCE_LABEL[sourceType] ?? SOURCE_LABEL.uploaded_media)[locale === "en-US" ? "en" : "zh"];

/** A star rating drawn as whole stars between 1 and 5. */
export const clampStars = (value) => Math.min(5, Math.max(1, Math.round(value || 1)));

/** The reader's own uploads, newest publication first (ties by id). */
export const sortUploaded = (items) => [...items].sort((left, right) => Date.parse(right.published_at) - Date.parse(left.published_at) || right.id.localeCompare(left.id));

/** The model a version's brief was made by: what the version recorded, or null. */
export function briefModel(version) {
  const provider = version?.model_manifest?.decision_provider;
  const model = provider && typeof provider === "object" ? provider.actual_model : null;
  return typeof model === "string" && model ? model : null;
}

/** The version a bare address opens: the newest forecast's newest version (null when the company has no forecast). */
export function latestVersionId(roots) {
  return roots?.[0]?.latest_version_id ?? null;
}

/** An http(s) address a link may point at (anything else is not drawn as a link). */
export function httpsUrl(value) {
  try { return typeof value === "string" && new URL(value.trim()).protocol === "https:" ? value.trim() : null; } catch { return null; }
}
