import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  ANSWER_FILTER_DEFAULTS, answerRow, answerNotes, answersQuery, answerStatus, costCell, deliveryRow, detailTimeline, dutyModeLine, dutyRow, formatMs, formatTime, formatTokens, formatUsd, operationRow, pagedQuery,
  slowRuleText, usageGroupLabel, usageQuery, usageRange, usageRow, usageTotalsRow,
} from "../src/backstage-view.mjs";
import { ANSWERS, DELIVERIES, DETAIL, DUTY, DETAIL_INCOMPLETE, DETAIL_OLD, OPERATIONS, usageAnswer } from "../tools/shots/fixtures/backstage.mjs";

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
  // The server's own word for the state wins: rows still being written are 记账中, never 未设价格.
  assert.deepEqual(costCell(null, true, "pending"), { kind: "pending", amount: "" });
  assert.deepEqual(costCell(0.01, true, "pending"), { kind: "pending", amount: "" }, "a partial sum of a turn still being booked is not its cost");
  assert.deepEqual(costCell(null, true, "unpriced"), { kind: "unpriced", amount: "" });
  assert.deepEqual(costCell(0.02, true, "unpriced"), { kind: "amount", amount: "$0.0200" });
  assert.deepEqual(costCell(null, true, "none"), { kind: "none", amount: "" });
  assert.deepEqual(costCell(0.5, true, "priced"), { kind: "amount", amount: "$0.50" });
  // Nothing was booked (older than the ledger, or rows lost): not a missing price, so not 未设价格.
  assert.deepEqual(costCell(null, true, "unrecorded"), { kind: "unrecorded", amount: "" });
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
  assert.deepEqual(answerRow({ ...ANSWERS.items[2], cost_state: undefined }, "UTC").cost, { kind: "unpriced", amount: "" }, "an answer from before cost_state existed behaves as it did");
  assert.equal(rows[2].time_taken, "1 min 2 s");
  assert.equal(rows[3].status.label, "没有完成");
  assert.deepEqual(rows[3].cost, { kind: "pending", amount: "" }, "the incomplete sample's ledger rows have not landed: 记账中");
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

test("detail: an ordered record is interleaved by its events, each with its offset; the question, card, card result and answer frame it", () => {
  const steps = detailTimeline(DETAIL, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "model", "model", "narration", "tool", "tool", "tool", "model", "narration", "card", "card_result", "answer"]);
  const [, first, second, narration, tool1, , tool3, third] = steps;
  assert.equal(first.title, "haiku-5.5");
  assert.equal(first.offset, "", "an attempt the timeline does not know has no time of its own");
  assert.equal(second.offset, "+1.7 s");
  assert.equal(narration.offset, "+1.7 s");
  assert.equal(tool1.offset, "+1.7 s");
  assert.equal(tool1.done_offset, "+2.4 s", "a tool shows when its result came back");
  assert.equal(tool3.done_offset, "", "no tool_done: the call did not finish");
  assert.equal(third.offset, "+4.4 s");
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

test("detail without events (an old record, or one from before the field) keeps the kind order and shows no offsets", () => {
  const { events, ordered, ...older } = DETAIL;
  const steps = detailTimeline(older, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "narration", "narration", "model", "model", "model", "tool", "tool", "tool", "card", "card_result", "answer"]);
  assert.ok(steps.every((s) => !s.offset));
  const unordered = detailTimeline({ ...DETAIL, ordered: false, events: [] }, "UTC");
  assert.deepEqual(unordered.map((s) => s.kind), steps.map((s) => s.kind));
});

test("events that point at nothing are skipped and what they left out still shows", () => {
  const steps = detailTimeline({ ...DETAIL, events: [{ kind: "narration", at_ms: 5, index: 99 }, { kind: "tool_done", at_ms: 6, call_id: "nope" }, { kind: "model_call", at_ms: 7, index: 2 }, "x", null] }, "UTC");
  assert.deepEqual(steps.filter((s) => s.kind === "model").length, 3, "every model call is shown once");
  assert.equal(steps.filter((s) => s.kind === "tool").length, 3);
  assert.equal(steps.filter((s) => s.kind === "narration").length, 2);
});

test("detail notes: backup model, the old-engine line, an unfinished turn, the Langfuse link", () => {
  assert.deepEqual(answerNotes(DETAIL).map((n) => n.text), ["改用备用模型：haiku-5.5 → gpt-6.1-terra（http_500）", "未设价格的调用缺：输入价、输出价"]);
  assert.equal(answerNotes({ ...DETAIL, cost_state: "priced" }).length, 1);
  assert.equal(answerNotes(DETAIL_OLD)[0].text, "旧流程的记录，只有部分经过");
  assert.equal(answerNotes(DETAIL_INCOMPLETE)[0].text, "这一轮没有答完，下面是它留下的记录");
  assert.equal(answerNotes(DETAIL).some((n) => n.kind === "langfuse"), false, "the link is its own field, not a note");
  assert.equal(answerNotes({ ...DETAIL, ordered: false, events: [{}, {}] }).some((n) => n.text === "这条记录没有时间顺序，按类别排列"), true);
  assert.equal(answerNotes({ ...DETAIL, ordered: false, events: [] }).some((n) => n.kind === "unordered"), false, "nothing to order, nothing to say");
  assert.equal(answerNotes({ ...DETAIL, ordered: undefined }).some((n) => n.kind === "unordered"), false, "an answer from before the field is not accused of being unordered");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "pending" }).find((n) => n.kind === "pending").text, "记账中：有些调用的费用还在写入，稍后再看");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "unpriced", missing_prices: ["input", "cache_read"] }).find((n) => n.kind === "unpriced").text, "未设价格的调用缺：输入价、缓存读取价");
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

test("free text cannot widen a table or the drawer, reads in its own direction, and the 未设价格 link does not open the row", () => {
  const table = src("app/backstage/BackstageTable.tsx"), drawer = src("app/backstage/AnswerDrawer.tsx");
  assert.match(table, /\[overflow-wrap:anywhere\]/);
  assert.match(table, /<span dir="auto"/);
  assert.match(table, /onClick=\{event => event\.stopPropagation\(\)\}/);
  assert.match(drawer, /\[overflow-wrap:anywhere\]/);
  assert.ok((drawer.match(/dir="auto"/g) ?? []).length >= 5);
  assert.match(drawer, /load\.data\?\.id === id/, "a detail is shown only under the id it was asked for");
  assert.match(src("app/backstage/UsageTab.tsx"), /load\.data\.group === group && load\.data\.from === range\.from && load\.data\.to === range\.to/, "usage numbers only under their own request");
  assert.match(src("app/backstage/use-paged.ts"), /items: \[\], next: null, extra: null, loading: true/, "a new filter clears the old rows at once");
});

test("unrecorded: a list row and a detail line say nothing was booked, never 未设价格; the detail explains it", () => {
  assert.deepEqual(answerRow({ ...ANSWERS.items[0], cost_usd: null, cost_state: "unrecorded" }, "UTC").cost, { kind: "unrecorded", amount: "" });
  const lines = detailTimeline({ ...DETAIL_INCOMPLETE, model_calls: [{ ...DETAIL_INCOMPLETE.model_calls[0], recorded: false }, { ...DETAIL_INCOMPLETE.model_calls[0] }] }, "UTC").filter((s) => s.kind === "model");
  assert.equal(lines[0].cost.kind, "unrecorded", "a call with no ledger row");
  assert.equal(lines[1].cost.kind, "unpriced", "a call with a row and no price");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "unrecorded", missing_prices: [] }).find((n) => n.kind === "unrecorded").text, "这一轮没有记账（早于记账功能，或记账丢失）");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "unrecorded" }).some((n) => n.kind === "unpriced"), false);
});

test("number cells never wrap, so long text beside them cannot squeeze them", () => {
  for (const file of ["AnswersTab", "UsageTab"]) assert.ok((src(`app/backstage/${file}.tsx`).match(/whitespace-nowrap/g) ?? []).length >= 5, file);
  assert.match(src("app/backstage/BackstageTable.tsx"), /font-mono tabular-nums whitespace-nowrap|whitespace-nowrap font-mono tabular-nums/);
});


test("duty: each decision and each way a wake-up ends has its word, and only a sent-or-not message says so", () => {
  const rows = DUTY.items.map((item) => dutyRow(item, "UTC"));
  assert.deepEqual(rows.map((row) => row.decision.label), ["告诉你", "攒进简报", "只记下", "不理会", "告诉你", "告诉你", "告诉你", "失败", "没有决定", "丢弃", "已关闭"]);
  assert.deepEqual(rows.map((row) => row.delivery), ["", "", "", "", "已发出", "超过今天的上限，没发", "发送失败", "", "", "", ""]);
  assert.deepEqual(rows.slice(0, 1).map((row) => [row.symbol, row.what, row.open, row.mode]), [["NVDA", "NVDA 盘中下跌 6.2%，跌破 20 日均线", DETAIL.message_id, "只观察"]]);
  assert.equal(rows[4].mode, "已开启");
  assert.equal(rows[10].mode, "已关闭");
  assert.equal(rows[7].open, null, "a wake-up with no recorded turn has nothing to open");
  assert.equal(rows[1].message, "");
  assert.deepEqual(dutyRow({}, "UTC").decision, { label: "—", kind: "neutral" });
});

test("duty: the mode line says the mode in the owner's words, and an unknown mode says nothing", () => {
  assert.equal(dutyModeLine("shadow"), "现在只观察：它会判断，但不会发消息给你。");
  assert.equal(dutyModeLine("on"), "已开启：『告诉你』的会按你的通道设置发出。");
  assert.equal(dutyModeLine("off"), "已关闭");
  assert.equal(dutyModeLine("???"), "");
  assert.equal(usageGroupLabel("purpose", { key: "duty", label: "duty" }), "值班");
});
