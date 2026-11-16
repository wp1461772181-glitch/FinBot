// Decisions of the single-forecast page (P6.2) as pure functions: which bottom tab, how a version was made, what changed against its parent, who may
// revise and with what, and the request refs a revision sends.  No React, no window, no network.  Strings that are zh-CN phrase keys are marked `phrase`.

export const DETAIL_SECTIONS = ["versions", "evaluation", "audit"];
export const SECTION_PHRASE = { versions: "版本对比", evaluation: "到期评估", audit: "审计与来源" };
export const MAX_REVISION_SOURCES = 10;

/** The bottom tab an address names (?section=).  The old #revisions address arrives as `versions`; anything else is the first tab. */
export function detailSection(value) {
  return DETAIL_SECTIONS.includes(value) ? value : "versions";
}

/** How one version of the chain came to be, from its record: no parent is the first version whatever its trigger says. */
export function versionMethod(entry) {
  if (!entry?.parent_version_id) return { key: "initial", phrase: "初始" };
  if (entry.trigger_type === "manual_revision") return { key: "manual", phrase: "人工修订" };
  if (entry.trigger_type === "automatic_monitor" || entry.trigger_type === "automatic_revision") return { key: "monitor", phrase: "新材料修订" };
  return { key: "update", phrase: "预测更新" };
}

function sourceId(item) {
  return `${String(item?.source_type ?? "unknown")}:${String(item?.source_id ?? item?.event_version_id ?? item?.id ?? "")}`;
}
function eventId(item) {
  return String(item?.event_version_id ?? item?.id ?? `${item?.source_type}:${item?.source_id}`);
}

/**
 * What the frozen source list of `current` holds against its parent's: added (new to this version), replaced (same source, a newer event),
 * removed (in the parent only) and inherited.  No parent: everything counts as the first list, nothing is compared.
 */
export function sourceDiff(current, parent) {
  const now = Array.isArray(current?.evidence_version_manifest) ? current.evidence_version_manifest : [];
  if (!parent) return { total: now.length, added: 0, replaced: 0, removed: 0, inherited: 0, hasParent: false };
  const before = Array.isArray(parent.evidence_version_manifest) ? parent.evidence_version_manifest : [];
  const byId = new Map(before.map((item) => [sourceId(item), item]));
  const ids = new Set(now.map(sourceId));
  const added = now.filter((item) => !byId.has(sourceId(item))).length;
  const replaced = now.filter((item) => { const prior = byId.get(sourceId(item)); return prior !== undefined && eventId(prior) !== eventId(item); }).length;
  const removed = before.filter((item) => !ids.has(sourceId(item))).length;
  return { total: now.length, added, replaced, removed, inherited: now.length - added - replaced, hasParent: true };
}

/** A fixed target date counts as expired once it is before `today` (UTC, YYYY-MM-DD); null when the date cannot be read.  The server still decides what may be revised. */
export function targetExpired(target, today) {
  if (typeof target !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(target)) return null;
  return target < today;
}

/** Whether a revision may start: only while the target is still ahead.  `reason` is a phrase key. */
export function reviseGate(target, today) {
  const expired = targetExpired(target, today);
  if (expired === false) return { allowed: true, reason: null };
  return { allowed: false, reason: expired === true ? "该预测的目标已到期，只能查看历史版本。" : "该预测的目标合同无效，只能查看历史版本。" };
}

/** The ids of the versions decided by another provider or model than their parent (needs both records; a version whose records are not read yet is left out). */
export function modelChangedIds(versions, details, changed) {
  const out = new Set();
  for (const version of Array.isArray(versions) ? versions : []) {
    const current = details.get(version.id);
    const parent = version.parent_version_id ? details.get(version.parent_version_id) : null;
    if (current && parent && changed(current, parent)) out.add(version.id);
  }
  return out;
}

const GROUPS = [
  { id: "new", phrase: "新发布材料", categories: ["new"] },
  { id: "backfilled", phrase: "过往补充材料", categories: ["backfilled", "preexisting"] },
  { id: "reanalyzed", phrase: "新完成分析", categories: ["reanalyzed"] },
  { id: "status", phrase: "来源状态更新", categories: null },
];

/** A candidate's category as the group it belongs to; every category the groups do not name is a source status update. */
export function candidateGroupId(category) {
  return (GROUPS.find((group) => group.categories?.includes(category)) ?? GROUPS[3]).id;
}

/** The candidates, grouped in the fixed order (new, backfilled, reanalyzed, status); inside a group the server's order.  Empty groups are left out. */
export function candidateGroups(options) {
  const list = Array.isArray(options) ? options : [];
  return GROUPS.map((group) => ({ id: group.id, phrase: group.phrase, items: list.filter((option) => candidateGroupId(option.revisionType) === group.id) })).filter((group) => group.items.length > 0);
}

/** Tick or untick one candidate.  Ticking past the cap changes nothing; the caller shows the cap as disabled boxes. */
export function toggleSource(keys, key, max = MAX_REVISION_SOURCES) {
  if (keys.includes(key)) return keys.filter((item) => item !== key);
  return keys.length >= max ? keys : [...keys, key];
}

/** A box is disabled when it is not ticked and the cap is reached. */
export function sourceDisabled(keys, key, max = MAX_REVISION_SOURCES) {
  return !keys.includes(key) && keys.length >= max;
}

/** The ticked candidates in the SERVER's order (not the order of the clicks): the order the old form sent them in, and the request body keeps it. */
export function pickedSources(options, keys) {
  return (Array.isArray(options) ? options : []).filter((option) => keys.includes(option.key));
}

/** The `source_refs` of a revision request, field for field what the old form sent. */
export function revisionRefs(options, keys) {
  return pickedSources(options, keys).map((source) => ({ source_type: source.source_type, source_id: source.source_id }));
}

/** The candidate an address's ?revise= names (a library filing), or null.  It is found to be shown, never to be ticked. */
export function reviseTarget(options, sourceIdLower) {
  if (!sourceIdLower) return null;
  return (Array.isArray(options) ? options : []).find((option) => option.source_type === "official_filing" && String(option.source_id).toLowerCase() === sourceIdLower) ?? null;
}

export const REVISE_STEPS = ["parent", "materials", "confirm"];

/** Whether the drawer may go on from a step: the parent is always set (the newest by default); the materials step needs at least one ticked. */
export function canContinue(step, { picked }) {
  if (step === "materials") return picked >= 1 && picked <= MAX_REVISION_SOURCES;
  return step !== "confirm";
}
