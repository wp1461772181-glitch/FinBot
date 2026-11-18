import assert from "node:assert/strict";
import test from "node:test";
import { arrangeChoices, answerSummary } from "../src/approval-card.mjs";
import { routinesBadge, waitingCount } from "../src/inbox-items.mjs";
import { confirmEntries, entryCard, liveCount } from "../src/routine-cards.mjs";
import { EXTRA_INBOX, EXTRA_PROPOSALS, INBOX, PROPOSALS } from "../tools/shots/fixtures/routines.mjs";

const confirms = INBOX.filter((item) => item.section === "confirm");

test("the live entries are exactly what the sidebar counts (routinesBadge), for the fixtures and for every mix of states", () => {
  const entries = confirmEntries([...PROPOSALS, ...EXTRA_PROPOSALS], [...confirms, ...EXTRA_INBOX]);
  assert.equal(liveCount(entries), routinesBadge([...PROPOSALS, ...EXTRA_PROPOSALS], [...confirms, ...EXTRA_INBOX]));
  assert.equal(liveCount(entries), 3);
  const states = ["unread", "read", "done", "dismissed"];
  for (const status of states) for (const expired of [false, true]) {
    const proposals = [{ ...PROPOSALS[0], expired }], items = [{ ...confirms[0], status }];
    assert.equal(liveCount(confirmEntries(proposals, items)), routinesBadge(proposals, items), `${status} ${expired}`);
  }
  assert.equal(liveCount(confirmEntries(null, undefined)), 0);
  assert.equal(routinesBadge(null, undefined), 0);
});

test("per bot, the same entries are what waitingCount says of the bot's card", () => {
  const entries = confirmEntries([...PROPOSALS, ...EXTRA_PROPOSALS], [...confirms, ...EXTRA_INBOX]);
  // waitingCount filters the proposals by bot but counts every open write (the old workspace card); only the proposals of the bot are comparable
  const bot = PROPOSALS[0].bot_id;
  assert.equal(entries.filter((e) => e.kind === "proposal" && e.phase === "live" && e.botId === bot).length, waitingCount(bot, PROPOSALS, []));
});

test("live first, the newest first; the expired proposals and the confirmed writes follow, also newest first; a dismissed write is not an entry", () => {
  const done = { ...confirms[0], id: "done-1", status: "done", created_at: "2026-11-13T09:00:00Z" };
  const dismissed = { ...confirms[0], id: "gone-1", status: "dismissed" };
  const entries = confirmEntries([...PROPOSALS, ...EXTRA_PROPOSALS], [...confirms, ...EXTRA_INBOX, done, dismissed]);
  assert.deepEqual(entries.map((e) => `${e.kind}:${e.phase}`), ["suggestion:live", "suggestion:live", "proposal:live", "suggestion:done", "proposal:expired"]);
  const live = entries.filter((e) => e.phase === "live").map((e) => Date.parse(e.createdAt));
  assert.deepEqual([...live].sort((a, b) => b - a), live);
  assert.ok(!entries.some((e) => e.id === "gone-1"));
});

test("a proposal's card has one press, the way to its conversation; nothing in it says 同意 (the press is in the conversation)", () => {
  const entry = confirmEntries(PROPOSALS, [])[0];
  const { card, layout } = entryCard(entry);
  assert.deepEqual(card.choices.map((c) => c.value), ["review"]);
  assert.equal(layout.primary.label, "去对话核对");
  assert.equal(layout.secondary, null);
  assert.deepEqual(layout.more, []);
  assert.equal(card.display.agent_suggestion, undefined);
  assert.equal(card.display.title, PROPOSALS[0].title);
  assert.equal(card.question, PROPOSALS[0].detail);
});

test("a suggested write's card: two main buttons (同意, 去对话核对) and the rest in 「…」; 打开对话 only when the run has a conversation", () => {
  const [plain, withConversation] = [confirmEntries([], confirms)[0], confirmEntries([], EXTRA_INBOX)[0]];
  const a = entryCard(plain), b = entryCard(withConversation);
  assert.deepEqual([a.layout.primary.label, a.layout.secondary.label], ["同意", "去对话核对"]);
  assert.deepEqual(a.layout.more.map((c) => c.label), ["跳过", "稍后", "忽略"]);
  assert.deepEqual(b.layout.more.map((c) => c.label), ["跳过", "稍后", "打开对话", "忽略"]);
  assert.equal(a.card.display.agent_suggestion, true);
  assert.equal(plain.token, "fixture-ref");
  assert.equal(plain.taskName, "周日组合复盘");
  // at most two main buttons, never a trade
  for (const { layout } of [a, b]) assert.ok([layout.primary, layout.secondary].filter(Boolean).length <= 2);
  assert.ok(![...a.card.choices, ...b.card.choices].some((c) => /买|卖|下单|交易/.test(c.label)));
});

test("a write already confirmed or skipped cannot be pressed again (the old buttons were disabled)", () => {
  const confirmed = entryCard(confirmEntries([], [{ ...confirms[0], confirmation_state: "confirmed" }])[0]);
  const skipped = entryCard(confirmEntries([], [{ ...confirms[0], confirmation_state: "skipped" }])[0]);
  assert.equal(confirmed.card.choices.find((c) => c.label === "同意").disabled, true);
  assert.equal(confirmed.card.choices.find((c) => c.label === "跳过").disabled, undefined);
  assert.equal(skipped.card.choices.find((c) => c.label === "跳过").disabled, true);
  assert.equal(skipped.card.choices.find((c) => c.label === "同意").disabled, undefined);
});

test("the folded line of a confirmed write says 已确认 (the card's own summary reads the 同意 choice as a confirmation)", () => {
  const { card } = entryCard(confirmEntries([], [{ ...confirms[0], status: "done" }])[0]);
  const label = card.choices.find((c) => c.value.startsWith("confirm:")).label;
  assert.equal(answerSummary(card, label).outcome, "confirmed");
  assert.equal(answerSummary(card, label).detail, card.display.title);
});

test("the arrangement is the card's own for a confirm card: the first choice is the main one, so the page's order is the card's order", () => {
  const { card, layout } = entryCard(confirmEntries([], confirms)[0]);
  assert.equal(arrangeChoices(card).primary.value, layout.primary.value);
});
