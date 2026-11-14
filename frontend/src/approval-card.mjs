// What the confirmation card (components/ApprovalCard.tsx) decides, apart from how it looks.  The rules of the cards themselves (titles, which
// choice goes out as what) stay in chat-clarification.mjs; this module only arranges them for the card: which buttons are the two main ones,
// how long a confirmation lives, what a finished card says of itself, and how many materials a revision card still wants ticked.

import { APPROVAL_TTL_MS } from "./approval-ttl.mjs";
export { APPROVAL_TTL_MS }; // a write confirmation lives ten minutes on the server (design 4.2); the card counts the same time down for a card made in this session

const WRITE_REASONS = new Set(["write_confirmation", "confirm_write", "choose_write_action", "choose_revision_sources"]);
const CONFIRM_REASONS = new Set(["write_confirmation", "confirm_write", "choose_revision_sources"]);

/** "revision": tick materials; "write": confirm or decline an action; "question": the bot asks and the choices are the answers. */
export function approvalKind(card) {
  if (card?.reason === "choose_revision_sources") return "revision";
  return WRITE_REASONS.has(card?.reason) ? "write" : "question";
}

/** True when the card asks for a write (the notes about the ten minutes and about changing the target belong to it). */
export function isWriteCard(card) { return WRITE_REASONS.has(card?.reason); }

/** True when the card's first choice confirms (a card that lists actions to pick from has no main button). */
export function isConfirmCard(card) { return CONFIRM_REASONS.has(card?.reason); }

const isCancel = (choice) => /^cancel(:|$)/.test(choice?.value ?? "");

/**
 * How the card's choices are laid out.  A confirm card has at most two main buttons, 同意 (the first choice) and 取消 (the choice that
 * cancels, else the last one); every other choice goes into the 「…」 menu.  Any other card lists its choices as the options of one question.
 */
export function arrangeChoices(card) {
  const choices = Array.isArray(card?.choices) ? card.choices : [];
  if (!isConfirmCard(card)) return { layout: "list", primary: null, secondary: null, more: [], list: choices };
  const primary = choices[0] ?? null;
  const rest = choices.slice(1);
  const secondary = rest.find(isCancel) ?? (rest.length ? rest[rest.length - 1] : null);
  return { layout: "confirm", primary, secondary, more: rest.filter((choice) => choice !== secondary), list: [] };
}

/** Milliseconds a confirmation made at `freshAt` still has at `now` (never negative). */
export function remainingMs(freshAt, now) { return Math.max(0, freshAt + APPROVAL_TTL_MS - now); }

/** 09:41 — whole seconds, rounded up so the last second still shows 00:01. */
export function formatRemaining(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/** The materials a revision card still needs ticked, and whether there is nothing to tick at all. */
export function pickState(card, pickedCount) {
  const options = Array.isArray(card?.options) ? card.options : [];
  const min = options.length ? (card?.select?.min ?? 1) : 0;
  return { min, max: options.length ? (card?.select?.max ?? options.length) : 0, picked: pickedCount, missing: Math.max(0, min - pickedCount), noCandidates: approvalKind(card) === "revision" && options.length === 0 };
}

const TARGET_LABELS = {
  symbol: "公司代码", title: "材料", url: "链接", source_type: "来源类型", accession_number: "申报编号", form: "表单类型", days: "天数",
  max_tasks: "最多处理", decision_date: "决策日", kind: "类型", record_id: "记录", document_id: "文档", version_id: "版本", candidate_id: "候选",
  approved: "审核结果", saved_date: "知识库日期", web_date: "网页日期", source_refs: "来源",
};
// Ids the reader has no use for: the card never prints them.
const HIDDEN_FIELDS = new Set(["source_id", "record_id", "document_id", "version_id", "candidate_id", "source_refs"]);

/** The card's targets as label / value pairs, one list per target; `label` is a Chinese phrase (the caller translates it), an unknown field keeps its own name. */
export function targetRows(display) {
  const targets = Array.isArray(display?.targets) ? display.targets : [];
  return targets.map((target) => Object.entries(target ?? {}).filter(([key]) => !HIDDEN_FIELDS.has(key)).map(([key, value]) => ({ key, label: TARGET_LABELS[key] ?? key, known: key in TARGET_LABELS, value: String(value) })))
    .filter((row) => row.length > 0);
}

/**
 * What the card says of itself once it is over.  `reply` is the user's line that followed it (the choice's own label, the 「用所选的 N 份材料修订」
 * line, or what they typed).  Returns { outcome, detail }: outcome "confirmed" | "cancelled" | "answered" | "skipped"; `detail` is the action's title for a
 * write card and the answer for a question.  "skipped": a write or revision card whose next line was something else the reader typed in the composer: the
 * card was never confirmed (and, no longer being the newest line, can no longer be pressed here).
 */
export function answerSummary(card, reply) {
  const text = String(reply ?? "").trim();
  const kind = approvalKind(card);
  const title = card?.display?.title || "";
  if (kind === "question") return { outcome: "answered", detail: text };
  const choice = (card?.choices ?? []).find((item) => item.label === text);
  if (choice && isCancel(choice)) return { outcome: "cancelled", detail: title };
  if (choice && /^confirm:/.test(choice.value)) return { outcome: "confirmed", detail: title };
  if (kind === "revision" && /^用所选的 \d+ 份材料修订$/.test(text)) return { outcome: "confirmed", detail: text };
  return { outcome: "skipped", detail: title };
}

/** True when `now` is past the end of a confirmation made at `freshAt`. */
export function isExpired(freshAt, now) { return remainingMs(freshAt, now) <= 0; }
