// The 待你确认 tab of the task page as data: the two lists the server gives (routine cards a bot proposed in a conversation, and the writes unattended runs
// suggested) become one list of entries, each with the card it is shown as.  Pure, so a node test holds it.
//
// Which entries are alive is `routinesBadge`'s rule (inbox-items.mjs, the number of the sidebar), written once more here only in the shape of a phase; the
// test holds the two together: the live entries of any two lists are as many as `routinesBadge` counts.  What a press does is not decided here (it is the old
// page's requests, in RoutinesPage's hands); this module only says which presses a card offers and arranges them as the confirmation card wants them.

/** The phase of an entry: "live" (waits for a press), "expired" (a proposal whose ten minutes are over), "done" (a write already confirmed).  Dismissed writes are not entries. */
export function confirmEntries(proposals, confirms) {
  const fromProposals = (Array.isArray(proposals) ? proposals : []).map((proposal) => ({
    key: `proposal:${proposal.id}`, kind: "proposal", id: proposal.id, botId: proposal.bot_id ?? null, title: proposal.title || "", detail: proposal.detail || "",
    targets: Array.isArray(proposal.targets) ? proposal.targets : [], taskName: "", createdAt: proposal.created_at ?? null, expiresAt: proposal.expires_at ?? null,
    conversationId: proposal.conversation_id ?? null, state: null, token: null, phase: proposal.expired ? "expired" : "live",
  }));
  const fromConfirms = (Array.isArray(confirms) ? confirms : []).filter((item) => item.status !== "dismissed").map((item) => ({
    key: `suggestion:${item.id}`, kind: "suggestion", id: item.id, botId: item.bot_id ?? null, title: item.payload?.display?.title || item.title || "", detail: item.body || "",
    targets: Array.isArray(item.payload?.display?.targets) ? item.payload.display.targets : [], taskName: item.payload?.task_name ?? "", createdAt: item.created_at ?? null, expiresAt: null,
    conversationId: item.conversation_id ?? null, state: item.confirmation_state ?? null, token: item.action_token ?? null, phase: item.status === "done" ? "done" : "live",
  }));
  const rank = (entry) => (entry.phase === "live" ? 0 : 1);
  const time = (entry) => Date.parse(entry.createdAt ?? "") || 0;
  return [...fromProposals, ...fromConfirms].sort((a, b) => rank(a) - rank(b) || time(b) - time(a));
}

/** How many entries wait for a press: the number the tab and the sidebar show. */
export function liveCount(entries) { return entries.filter((entry) => entry.phase === "live").length; }

/** A choice of a card: `value` is what the page dispatches on, `label` a Chinese phrase (the card translates it). */
const choice = (value, label, disabled = false) => ({ value, label, ...(disabled ? { disabled: true } : {}) });

/**
 * The confirmation card of an entry and how its presses are arranged (components/ApprovalCard.tsx takes both).  A proposal's only press is the way to its
 * conversation, where its card is: 去对话核对 (the clock of its ten minutes is the server's: `expired` says when they are over, the card counts nothing down, so the list and the sidebar never disagree).  A suggested write has 同意 (it runs now), 去对话核对 (a card is made in the run's conversation and opened),
 * and in 「…」 the rest: 跳过, 稍后再说, 打开对话 (when the run has one), 忽略.  The two main buttons come first.
 */
export function entryCard(entry) {
  const proposal = entry.kind === "proposal";
  const targets = entry.targets.filter((target) => target && typeof target === "object");
  const card = {
    request_id: entry.id, reason: "write_confirmation", question: entry.detail || undefined,
    display: { title: entry.title || undefined, targets, ...(proposal ? {} : { agent_suggestion: true }) },
    choices: proposal ? [choice("review", "去对话核对")]
      : [choice("confirm:inbox", "同意", entry.state === "confirmed"), choice("review", "去对话核对"), choice("skip", "跳过", entry.state === "skipped"), choice("later", "稍后再说"), ...(entry.conversationId ? [choice("open", "打开对话")] : []), choice("dismiss", "忽略")],
  };
  const [primary, secondary, ...more] = card.choices;
  return { card, layout: { layout: "confirm", primary, secondary: secondary ?? null, more, list: [] } };
}
