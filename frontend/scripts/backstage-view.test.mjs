import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  ANSWER_FILTER_DEFAULTS, answerRow, answerNotes, answersQuery, answerStatus, costCell, deliveryRow, detailTimeline, formatMs, formatTime, formatTokens, formatUsd, operationRow, pagedQuery,
  slowRuleText, usageGroupLabel, usageQuery, usageRange, usageRow, usageTotalsRow,
} from "../src/backstage-view.mjs";
import { ANSWERS, DELIVERIES, DETAIL, DETAIL_INCOMPLETE, DETAIL_OLD, OPERATIONS, usageAnswer } from "../tools/shots/fixtures/backstage.mjs";

const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");

test("the answers query carries only the filters that are set, and 'only high tier' and 'only slow' are the API's tier=high and slow=1", () => {
  assert.equal(answersQuery(ANSWER_FILTER_DEFAULTS), "");
  assert.equal(answersQuery({ ...ANSWER_FILTER_DEFAULTS, botId: "b1", engine: "v2", status: "failed", highTier: true, slow: true, q: " 营收 ", before: "1.x" }),
    "?bot_id=b1&engine=v2&status=failed&tier=high&slow=1&q=%E8%90%A5%E6%94%B6&before=1.x");
  assert.equal(answersQuery({ ...ANSWER_FILTER_DEFAULTS, q: "x".repeat(150) }), `?q=${"x".repeat(100)}`, "the API takes 100 characters at most");
  assert.equal(pagedQuery("abc"), "?before=abc");
  assert.equal(pagedQuery(null), "");
});

test("statuses read in words, incomplete included; an unknown one is shown as it came", () => {
  assert.deepEqual(answerStatus("succeeded"), { label: "已回答", kind: "success" });
  assert.deepEqual(answerStatus("failed"), { label: "失败", kind: "failure" });
  assert.deepEqual(answerStatus("cancelled"), { label: "已取消", kind: "neutral" });
  assert.deepEqual(answerStatus("waiting_for_input"), { label: "等你回复", kind: "action" });
  assert.deepEqual(answerStatus("incomplete"), { label: "没有完成", kind: "failure" });
  assert.deepEqual(answerStatus("zzz"), { label: "zzz", kind: "neutral" });
});

test("cost: a number is a dollar figure; null with calls is 未设价格, never a made-up number; no calls is a dash", () => {
  assert.deepEqual(costCell(0.0123, true), { kind: "amount", amount: "$0.0123" });
  assert.deepEqual(costCell(0.5, true), { kind: "amount", amount: "$0.50" });
  assert.deepEqual(costCell(0, true), { kind: "amount", amount: "$0.00" });
  assert.deepEqual(costCell(null, true), { kind: "unpriced", amount: "" });
  assert.deepEqual(costCell(null, false), { kind: "none", amount: "" });
  assert.equal(formatUsd(1234.5), "$1,234.50");
  assert.equal(formatUsd(0.00004), "$0.00004");
});

test("durations and token counts", () => {
  assert.equal(formatMs(null), "—");
  assert.equal(formatMs(850), "850 ms");
  assert.equal(formatMs(2500), "2.5 s");
  assert.equal(formatMs(61500), "1 min 2 s");
  assert.equal(formatTokens(null), "—");
  assert.equal(formatTokens(1870), "1,870");
  assert.equal(formatTokens(1234567), "1,234,567");
  assert.equal(formatTime("2026-11-13T01:50:02+00:00", "UTC"), "11-13 01:50");
  assert.equal(formatTime(null, "UTC"), "—");
  assert.equal(formatTime("nonsense", "UTC"), "—");
});

test("answers tab: each sample row becomes the cells the table shows", () => {
  const rows = ANSWERS.items.map((row) => answerRow(row, "UTC"));
  assert.equal(rows.length, 5);
  assert.deepEqual(rows[0], { id: ANSWERS.items[0].message_id, time: "11-13 01:50", bot: "FinBot", question: "TSLA 最近一个季度的营收是多少？", status: { label: "已回答", kind: "success" }, tier: "低档",
    time_taken: "4.2 s", calls: "2", tokens: "1,870", cost: { kind: "amount", amount: "$0.0123" }, old_engine: false });
  assert.equal(rows[1].status.label, "等你回复");
  assert.equal(rows[1].tier, "中档");
  assert.equal(rows[2].tier, "高档");
  assert.deepEqual(rows[2].cost, { kind: "unpriced", amount: "" }, "cost null on a turn that called models: 未设价格");
  assert.equal(rows[2].time_taken, "1 min 2 s");
  assert.equal(rows[3].status.label, "没有完成");
  assert.equal(rows[3].tier, "—");
  assert.equal(rows[3].time_taken, "—");
  assert.equal(rows[4].old_engine, true, "an old-engine row says so");
  assert.deepEqual(rows[4].cost, { kind: "none", amount: "" }, "no model call is recorded for it, so no cost either");
  assert.equal(rows[4].tokens, "—");
});

test("a row whose bot is gone and a question that is empty still have something to show", () => {
  const row = answerRow({ ...ANSWERS.items[0], bot_name: null, question: "" }, "UTC");
  assert.equal(row.bot, "—");
  assert.equal(row.question, "（没有问题文字）");
});

test("slow rule text names the threshold; without a threshold it says nothing was slow enough to judge", () => {
  assert.equal(slowRuleText(2400), "慢的标准：耗时高于本页回答的 90 分位（2.4 s）");
  assert.equal(slowRuleText(null), "");
});

test("detail: a timeline in time order with the question, narration, model calls, tool calls, the card pressed, and the answer", () => {
  const steps = detailTimeline(DETAIL, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "narration", "narration", "model", "model", "model", "tool", "tool", "tool", "card", "card_result", "answer"]);
  const [, , , first, second, third] = steps;
  assert.equal(first.title, "haiku-5.5");
  assert.equal(first.tier, "低档");
  assert.equal(first.ok, false);
  assert.equal(first.error, "http_500");
  assert.equal(second.attempt, 2, "a retry shows as its own row");
  assert.equal(second.cost.kind, "amount");
  assert.equal(first.cost.kind, "none", "a failed call that used no tokens has no cost to show");
  assert.equal(third.tokens, "3,080");
  assert.equal(third.cost.kind, "unpriced", "tokens without a price: 未设价格");
  const tools = steps.filter((s) => s.kind === "tool");
  assert.equal(tools[0].title, "研究队列");
  assert.equal(tools[0].result, "成功，共 7 条：AAPL、TSLA、NVDA");
  assert.equal(tools[1].arguments, '{"symbol":"ANT"}');
  assert.equal(tools[1].result, "失败：needs_confirmation");
  assert.equal(tools[2].result, "没有结果记录");
  assert.equal(tools[2].state, "unfinished");
  const card = steps.find((s) => s.kind === "card");
  assert.equal(card.title, "确认以下操作");
  assert.deepEqual(card.targets, ["ANT · 加入研究队列"]);
  assert.deepEqual(card.choices, ["同意", "取消"], "the card's choices are shown as labels only");
  assert.equal(steps.find((s) => s.kind === "card_result").title, "已完成");
  assert.equal(steps.at(-1).text, "我已提出这个操作，等你在卡片上确认。");
});

test("detail notes: backup model, the old-engine line, an unfinished turn, the Langfuse link", () => {
  assert.deepEqual(answerNotes(DETAIL).map((n) => n.text), ["改用备用模型：haiku-5.5 → gpt-6.1-terra（http_500）"]);
  assert.equal(answerNotes(DETAIL).length, 1);
  assert.equal(answerNotes(DETAIL_OLD)[0].text, "旧流程的记录，只有部分经过");
  assert.equal(answerNotes(DETAIL_INCOMPLETE)[0].text, "这一轮没有答完，下面是它留下的记录");
  assert.equal(answerNotes(DETAIL).some((n) => n.kind === "langfuse"), false, "the link is its own field, not a note");
});

test("detail of an old-engine record is a short timeline, not an error", () => {
  const steps = detailTimeline(DETAIL_OLD, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "answer"]);
  const unfinished = detailTimeline(DETAIL_INCOMPLETE, "UTC");
  assert.deepEqual(unfinished.map((s) => s.kind), ["question", "model", "tool"], "no answer step when no answer was given");
  assert.equal(unfinished[2].result, "没有结果记录");
});

test("detail copes with missing parts (null, wrong types)", () => {
  const steps = detailTimeline({ question: "q", model_calls: null, narration: "x", tool_calls: [null, { name: 5 }], card: "x", answer: null }, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "tool"]);
  assert.deepEqual(detailTimeline(null, "UTC"), []);
});

test("usage: ranges are UTC days; 7 days ends today and starts six days before", () => {
  assert.deepEqual(usageRange(7, "2026-11-13"), { from: "2026-11-07", to: "2026-11-13" });
  assert.deepEqual(usageRange(30, "2026-11-13"), { from: "2026-10-15", to: "2026-11-13" });
  assert.equal(usageQuery({ from: "2026-11-01", to: "2026-11-03", group: "model" }), "?from=2026-11-01&to=2026-11-03&group=model");
  assert.equal(usageQuery({ from: "", to: "", group: "day" }), "?group=day");
});

test("usage rows: tokens, p50, cost, and which prices are missing", () => {
  const payload = usageAnswer("day");
  const rows = payload.groups.map((g) => usageRow(g, "day"));
  assert.deepEqual(rows[0], { key: "2026-11-11", label: "2026-11-11", calls: "31", failed: "1", input: "82,000", output: "9,100", cache: "40,000 / 6,000", p50: "1.8 s", cost: { kind: "amount", amount: "$0.31" }, missing: [], unpriced_calls: 0 });
  assert.deepEqual(rows[1].missing, ["缓存读取价", "缓存写入价"]);
  assert.equal(rows[1].unpriced_calls, 6);
  assert.equal(rows[1].cost.kind, "amount", "priced calls are still summed; the unpriced count and the missing prices come beside it");
  const byModel = usageAnswer("model").groups.map((g) => usageRow(g, "model"));
  assert.deepEqual(byModel[2].cost, { kind: "unpriced", amount: "" });
  assert.deepEqual(byModel[2].missing, ["缓存读取价", "缓存写入价", "输入价", "输出价"], "in the order the API names them (sorted by key)");
  const totals = usageTotalsRow(payload.totals);
  assert.equal(totals.label, "合计");
  assert.equal(totals.calls, "101");
  assert.equal(totals.unpriced_calls, 6);
});

test("usage labels: purposes and the no-bot group are readable; day, model and bot keep what the API says", () => {
  assert.equal(usageGroupLabel("purpose", { key: "judge", label: "judge" }), "核查");
  assert.equal(usageGroupLabel("purpose", { key: "material_analysis", label: "material_analysis" }), "材料分析");
  assert.equal(usageGroupLabel("purpose", { key: "something_new", label: "something_new" }), "something_new");
  assert.equal(usageGroupLabel("bot", { key: "none", label: "（无）" }), "（无）");
  assert.equal(usageGroupLabel("model", { key: "haiku-5.5", label: "haiku-5.5" }), "haiku-5.5");
  assert.equal(usageGroupLabel("day", { key: "2026-11-11", label: "2026-11-11" }), "2026-11-11");
});

test("operations: what, status, decided at, result; a lapsed card nobody touched says 已过期，未处理", () => {
  const rows = OPERATIONS.items.map((o) => operationRow(o, "UTC"));
  assert.equal(rows[0].what, "确认以下操作");
  assert.equal(rows[0].detail, "加入研究队列 · ANT 加入研究队列");
  assert.deepEqual(rows[0].status, { label: "已完成", kind: "success" });
  assert.equal(rows[0].decided_at, "11-13 01:22");
  assert.equal(rows[0].result, "成功");
  assert.deepEqual(rows[1].status, { label: "已过期，未处理", kind: "neutral" });
  assert.equal(rows[1].decided_at, "—");
  assert.equal(rows[1].result, "—");
  assert.deepEqual(rows[2].status, { label: "已取消", kind: "neutral" });
  assert.equal(rows[3].result, "失败：invalid_price");
  const pressedLate = operationRow({ ...OPERATIONS.items[1], decided_at: "2026-11-12T13:00:00+00:00" }, "UTC");
  assert.equal(pressedLate.status.label, "已过期", "a lapsed card somebody pressed is expired, not 'untouched'");
  assert.equal(operationRow({ ...OPERATIONS.items[1], expired: false }, "UTC").status.label, "等待确认");
});

test("deliveries: time, source, channel, status, acknowledged", () => {
  const rows = DELIVERIES.items.map((d) => deliveryRow(d, "UTC"));
  assert.deepEqual(rows[0], { id: DELIVERIES.items[0].id, time: "11-13 01:00", source: "提醒", channel: "Telegram", status: { label: "已发送", kind: "success" }, acked: "11-13 01:05", text: "NVDA 上穿了你设的 125 美元价格线。" });
  assert.equal(rows[1].source, "任务");
  assert.equal(rows[1].channel, "微信");
  assert.equal(rows[1].acked, "未确认");
  assert.deepEqual(rows[2].status, { label: "发送失败", kind: "failure" });
  assert.equal(rows[2].acked, "—");
  assert.deepEqual(rows[3].status, { label: "过期未发", kind: "failure" });
  assert.deepEqual(rows[4].status, { label: "等待发送", kind: "progress" });
  assert.deepEqual(deliveryRow({ ...DELIVERIES.items[0], status: "sent", failure: "partial", source: "x", channel: "y" }, "UTC").status, { label: "部分送达", kind: "action" });
  assert.equal(deliveryRow({ ...DELIVERIES.items[0], source: "x", channel: "y" }, "UTC").source, "x", "an unknown source is shown as it came");
});

test("the page is wired in: route, owner-only navigation, a read-only page", () => {
  const sidebar = src("app/shell/AppSidebar.tsx"), more = src("app/shell/MoreDrawer.tsx"), router = src("app/router.tsx");
  assert.match(sidebar, /\{props\.personal && <NavLeaf area="backstage" props=\{props\} \/>\}/, "the entry is the owner's");
  assert.match(more, /props\.personal && .*paths\.backstage\(\)/s, "the phone's 更多 lists it for the owner only");
  assert.match(router, /PATTERNS\.backstageTab/);
  assert.match(router, /PATTERNS\.backstage,/);
  const api = src("api/backstage.ts");
  assert.doesNotMatch(api, /method:\s*"(POST|PUT|PATCH|DELETE)"/, "no write is made from the page");
  for (const file of ["BackstagePage", "AnswersTab", "AnswerDrawer", "UsageTab", "OperationsTab", "DeliveriesTab"]) assert.doesNotMatch(src(`app/backstage/${file}.tsx`), /method:\s*"(POST|PUT|PATCH|DELETE)"|<form|type="submit"/, file);
});
