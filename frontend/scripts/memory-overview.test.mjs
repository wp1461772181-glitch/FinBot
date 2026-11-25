import assert from "node:assert/strict";
import test from "node:test";
import { exportFilename, jobLine, jobOutcome, summaryLine, typedOnPage, viewGroups, viewWriteError } from "../src/memory-overview.mjs";

const v = (id, status, created_at, extra = {}) => ({ id, status, created_at, ended_at: null, text: id, quote: id, conversation_id: "c1", ...extra });
const company = (symbol, versions, current = undefined) => ({ symbol, name: symbol, versions, current: current === undefined ? versions.find(x => x.status === "active") ?? null : current });

test("the head lists the nine counts in order, keeps zeros, and a missing number is 0", () => {
  const line = summaryLine({ said: 3, typed: 0, inferred: 2, guesses_confirmed: 1, guesses_waiting: 0, archived: 4, views_current: 2, views_companies: 3, watch: 5 });
  assert.deepEqual(line.map(x => x.key), ["said", "typed", "inferred", "guesses_confirmed", "guesses_waiting", "archived", "views_current", "views_companies", "watch"]);
  assert.deepEqual(line.map(x => x.value), [3, 0, 2, 1, 0, 4, 2, 3, 5]);
  assert.equal(line.find(x => x.key === "guesses_waiting").label, "待你确认的推测");
  assert.equal(summaryLine({ said: 1 }).find(x => x.key === "watch").value, 0);
  assert.equal(summaryLine({ said: "x" }).find(x => x.key === "said").value, 0);
});

test("no counts is an empty head, not a row of zeros", () => {
  assert.deepEqual(summaryLine(null), []);
  assert.deepEqual(summaryLine(undefined), []);
  assert.deepEqual(summaryLine("nope"), []);
});

test("companies with a current view come first, newest current first; the rest follow by their newest version", () => {
  const nvda = company("NVDA", [v("n1", "dropped", "2026-10-03T00:00:00Z"), v("n3", "active", "2026-11-08T00:00:00Z"), v("n2", "superseded", "2026-10-28T00:00:00Z")]);
  const tsla = company("TSLA", [v("t1", "active", "2026-11-11T00:00:00Z")]);
  const amd = company("AMD", [v("a1", "archived", "2026-11-20T00:00:00Z")]);
  const old = company("INTC", [v("i1", "dropped", "2026-09-01T00:00:00Z")]);
  const groups = viewGroups([old, nvda, amd, tsla]);
  assert.deepEqual(groups.current.map(c => c.symbol), ["TSLA", "NVDA"]);
  assert.deepEqual(groups.former.map(c => c.symbol), ["AMD", "INTC"]);
});

test("a company's versions are put newest first and its history leaves out the current one", () => {
  const nvda = company("NVDA", [v("n1", "dropped", "2026-10-03T00:00:00Z"), v("n3", "active", "2026-11-08T00:00:00Z"), v("n2", "superseded", "2026-10-28T00:00:00Z")]);
  const [one] = viewGroups([nvda]).current;
  assert.deepEqual(one.versions.map(x => x.id), ["n3", "n2", "n1"]);
  assert.equal(one.current.id, "n3");
  assert.deepEqual(one.history.map(x => x.id), ["n2", "n1"]);
});

test("a company with only ended versions has no current and all of them as history; a current the server missed is found among the versions", () => {
  const [gone] = viewGroups([company("AMD", [v("a1", "superseded", "2026-10-01T00:00:00Z"), v("a2", "archived", "2026-11-01T00:00:00Z")])]).former;
  assert.equal(gone.current, null);
  assert.deepEqual(gone.history.map(x => x.id), ["a2", "a1"]);
  const [found] = viewGroups([company("AMD", [v("a1", "active", "2026-10-01T00:00:00Z")], null)]).current;
  assert.equal(found.current.id, "a1");
  assert.deepEqual(found.history, []);
});

test("bad input makes empty groups; a row without a symbol is skipped", () => {
  assert.deepEqual(viewGroups(null), { current: [], former: [] });
  assert.deepEqual(viewGroups([]), { current: [], former: [] });
  assert.deepEqual(viewGroups([null, { versions: [] }, "x"]), { current: [], former: [] });
  assert.deepEqual(viewGroups([{ symbol: "AAPL" }]).former.map(c => c.symbol), ["AAPL"]);
});

test("a view with no conversation was typed on the page", () => {
  assert.equal(typedOnPage({ conversation_id: null }), true);
  assert.equal(typedOnPage({}), true);
  assert.equal(typedOnPage({ conversation_id: "c1" }), false);
  assert.equal(typedOnPage(null), false);
});

test("a refused view write says what the owner can fix: at least four characters, or why it cannot be saved", () => {
  assert.equal(viewWriteError(422, "view_quote_too_short"), "至少写四个字");
  assert.equal(viewWriteError(422, "company_not_recognized"), "没认出这家公司。");
  assert.equal(viewWriteError(422, "invalid_view_text"), "这条看法没法保存：内容为空或太长。");
  assert.equal(viewWriteError(404, "view_not_found"), "这条已不存在。");
  assert.equal(viewWriteError(403, "owner_only"), "登录个人聊天后才能修改你的看法。");
  assert.equal(viewWriteError(500, null), "保存失败，请重试。");
  assert.equal(viewWriteError(422, "something_new"), "保存失败，请重试。");
  assert.equal(viewWriteError(undefined), "保存失败，请重试。");
});

const NOW = new Date("2026-11-25T04:00:00Z");

test("the monthly line says around when, and how many more messages bring it forward; the quarterly line is on its date, with the year when it is next year", () => {
  assert.equal(jobLine({ job: "monthly_review", next_due: "2026-12-25T01:00:00Z", messages_until_early: 12 }, "zh-CN", NOW), "下次每月整理：12月25日前后（再发 12 条消息会提前）");
  assert.equal(jobLine({ job: "monthly_review", next_due: "2026-12-25T01:00:00Z", messages_until_early: 0 }, "zh-CN", NOW), "下次每月整理：12月25日前后");
  assert.equal(jobLine({ job: "monthly_review", next_due: "2026-12-25T01:00:00Z" }, "zh-CN", NOW), "下次每月整理：12月25日前后");
  assert.equal(jobLine({ job: "quarterly_settle", next_due: "2027-02-15T01:00:00Z" }, "zh-CN", NOW), "下次每季整理：2027年2月15日");
  assert.equal(jobLine({ job: "quarterly_settle", next_due: "2026-12-31T01:00:00Z" }, "zh-CN", NOW), "下次每季整理：12月31日");
});

test("the job lines read in English too; a due date is the owner's Beijing day", () => {
  assert.equal(jobLine({ job: "monthly_review", next_due: "2026-12-25T01:00:00Z", messages_until_early: 1 }, "en-US", NOW), "Next monthly tidy: around 12/25 (1 more message brings it forward)");
  assert.equal(jobLine({ job: "monthly_review", next_due: "2026-12-25T01:00:00Z", messages_until_early: 3 }, "en-US", NOW), "Next monthly tidy: around 12/25 (3 more messages bring it forward)");
  assert.equal(jobLine({ job: "quarterly_settle", next_due: "2027-02-15T01:00:00Z" }, "en-US", NOW), "Next quarterly tidy: 2/15/2027");
  assert.equal(jobLine({ job: "quarterly_settle", next_due: "2026-12-31T17:00:00Z" }, "zh-CN", NOW), "下次每季整理：2027年1月1日");
});

test("a job with no due date says it is not scheduled; an unknown job uses the server's title", () => {
  assert.equal(jobLine({ job: "monthly_review", next_due: null }, "zh-CN", NOW), "下次每月整理：还没排定");
  assert.equal(jobLine({ job: "monthly_review", next_due: "garbage" }, "zh-CN", NOW), "下次每月整理：还没排定");
  assert.equal(jobLine({ job: "new_job", title: "新的整理", next_due: "2026-12-01T01:00:00Z" }, "zh-CN", NOW), "下次新的整理：12月1日");
  assert.equal(jobLine(null, "zh-CN", NOW), "下次：还没排定");
});

test("the last outcome is said in a few words; a job that has not run says nothing", () => {
  assert.equal(jobOutcome({ last_outcome: "done" }), "上次整理完成");
  assert.equal(jobOutcome({ last_outcome: "skipped", last_reason: "消息太少" }), "上次跳过：消息太少");
  assert.equal(jobOutcome({ last_outcome: "skipped", last_reason: null }), "上次跳过");
  assert.equal(jobOutcome({ last_outcome: "failed", last_reason: "ran_badly" }), "上次出错，稍后重试");
  assert.equal(jobOutcome({ last_outcome: null }), "");
  assert.equal(jobOutcome({ last_outcome: "mystery" }), "");
  assert.equal(jobOutcome(null), "");
  assert.equal(jobOutcome({ last_outcome: "skipped", last_reason: "too few" }, "en-US"), "Last tidy: skipped: too few");
});

test("the download is named finbot-memory-YYYYMMDD with the UTC date; anything but md is json", () => {
  const at = new Date("2026-11-25T23:30:00Z");
  assert.equal(exportFilename("json", at), "finbot-memory-20261125.json");
  assert.equal(exportFilename("md", at), "finbot-memory-20261125.md");
  assert.equal(exportFilename("pdf", at), "finbot-memory-20261125.json");
  assert.match(exportFilename("md"), /^finbot-memory-\d{8}\.md$/);
  assert.match(exportFilename("md", "bad"), /^finbot-memory-\d{8}\.md$/);
});
