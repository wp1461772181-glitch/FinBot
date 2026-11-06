import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  DEFAULT_REASON_KEY, EVIDENCE_KEYS, HINT_KEYS, REASON_KEYS, evidenceText, followUpQuestion, hintText, lineKey, markUnverified, matchLines,
  normalizeUnverified, parseFlagHref, plainSentence, reasonKey,
} from "../src/chat-unverified.mjs";

const labels = { insufficient: "证据不足", numbers: "数字未核实", reason: (code) => `原因:${code}` };
const answer = "AMD 收盘价为 100 美元 [1]。\nAMD 成交量为 999 万股 [1]。\n\n（另有 1 处表述未能与来源核对，已保留并标注“证据不足”。）";
const items = [{ line: "AMD 成交量为 999 万股 [1]。", reason: "unsupported_numeric_claim", numbers: ["999 万"] }];

test("only the reported sentence is matched, whatever its markers say", () => {
  assert.deepEqual(matchLines(answer, items), [-1, 0, -1, -1]);
  assert.deepEqual(matchLines("AMD 成交量为 999 万股 [2][3]。", items), [0]);
  assert.equal(lineKey("- **AMD** 成交量 [1]"), "**AMD**成交量");
});

test("a flag is appended to the sentence and the sentence itself is untouched", () => {
  const marked = markUnverified(answer, items, labels).split("\n");
  assert.equal(marked[0], "AMD 收盘价为 100 美元 [1]。");
  assert.ok(marked[1].startsWith("AMD 成交量为 999 万股 [1]。 [证据不足：原因:unsupported_numeric_claim](#unverified-0)"));
  assert.ok(marked[1].includes("[数字未核实：999 万](#unverified-num-0)"));
  assert.equal(marked[3], answer.split("\n")[3]);
});

test("a number found in a source gets the evidence flag only", () => {
  const marked = markUnverified("营收 10 亿 [1]。", [{ line: "营收 10 亿 [1]。", reason: "invalid_citation", numbers: [] }], labels);
  assert.ok(marked.includes("(#unverified-0)") && !marked.includes("#unverified-num-"));
});

test("list items match without their bullet and table rows keep their closing bar", () => {
  const text = "- 开盘价 998 美元 [1]\n| 成交量 | 999 万股 [1] |";
  const list = [{ line: "开盘价 998 美元", reason: "missing_citation" }, { line: "| 成交量 | 999 万股 [1] |", reason: "unsupported_numeric_claim" }];
  const [bullet, row] = markUnverified(text, list, labels).split("\n");
  assert.ok(bullet.startsWith("- 开盘价 998 美元 [1] [证据不足"));
  assert.ok(row.startsWith("| 成交量 | 999 万股 [1] [证据不足") && row.endsWith("|"));
});

test("the same sentence written twice is flagged once per report, and unreported text is never flagged", () => {
  const twice = "同一句 100 [1]。\n同一句 100 [1]。";
  assert.deepEqual(matchLines(twice, [{ line: "同一句 100 [1]。", reason: "x" }]), [0, -1]);
  assert.equal(markUnverified("没问题 [1]。", [], labels), "没问题 [1]。");
  assert.equal(markUnverified("没问题 [1]。", [{ line: "别的句子", reason: "x" }], labels), "没问题 [1]。");
});

test("a line the server shortened to its first 400 characters still matches", () => {
  const long = "很长的一句话".repeat(80);
  const [row] = matchLines(`${long} [1]。`, [{ line: long.slice(0, 400), reason: "x" }]);
  assert.equal(row, 0);
});

test("flag links, reasons and the follow-up question", () => {
  assert.deepEqual(parseFlagHref("#unverified-3"), { kind: "insufficient", index: 3 });
  assert.deepEqual(parseFlagHref("#unverified-num-3"), { kind: "numbers", index: 3 });
  assert.equal(parseFlagHref("#citation-3"), null);
  assert.equal(reasonKey("missing_citation"), REASON_KEYS.missing_citation);
  assert.equal(reasonKey("something_new"), DEFAULT_REASON_KEY);
  assert.equal(plainSentence("- AMD 成交量为 999 万股 [1]。"), "AMD 成交量为 999 万股。");
  assert.equal(followUpQuestion("AMD 成交量为 999 万股 [1]。"), "这句话的依据是什么：AMD 成交量为 999 万股。");
});

test("malformed reports are ignored", () => {
  assert.deepEqual(normalizeUnverified(null), []);
  assert.deepEqual(normalizeUnverified([null, { line: 3 }, { line: "   " }, { line: "有效 [1]", numbers: ["1", 2, " "] }]), [{ line: "有效 [1]", reason: "", numbers: ["1"] }]);
});

test("every reason text used by the badges has an English translation", async () => {
  const english = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
  const chinese = JSON.parse(await readFile(new URL("../src/locales/zh-CN.json", import.meta.url), "utf8"));
  for (const key of [...new Set([...Object.values(REASON_KEYS), ...Object.values(HINT_KEYS), ...Object.values(EVIDENCE_KEYS), DEFAULT_REASON_KEY, "证据不足", "数字未核实", "追问依据"])]) {
    assert.ok(chinese.includes(key), `zh-CN is missing: ${key}`);
    assert.ok(english[key]?.trim(), `en-US is missing: ${key}`);
  }
});

test("a figure the number review read from a source is a hint that names its source, never 「已核实」", () => {
  const item = { line: "利率下调 0.5% [1]。", reason: "number_read_from_source", numbers: [], ordinal: 1,
    evidence: [{ kind: "found", figure: "0.5%", ordinal: 1, quote: "cut its rate by half a percentage point", read_as: "0.5%" }] };
  assert.equal(hintText(item), "这句里的数字在 [1] 等来源中有依据，依据如下，请自行判断");
  const marked = markUnverified("利率下调 0.5% [1]。", [item], { ...labels, hint: (found) => hintText(found) });
  assert.ok(!marked.includes("证据不足") && !marked.includes("已核实"));
  assert.ok(marked.includes("(#unverified-0)") && marked.includes("(#unverified-ev-0)"));
  assert.ok(marked.includes("写作「cut its rate by half a percentage point」，读作 0.5%"));
});

test("evidence lines say what a source writes or how a figure is derived, and keep a dollar sign and a table bar as written", () => {
  assert.equal(evidenceText({ kind: "found", figure: "0.5%", ordinal: 2, quote: "costs $5 | half", read_as: "0.5%" }),
    "来源 [2] 写作「costs $5 ｜ half」，读作 0.5%");
  assert.equal(evidenceText({ kind: "derived", figure: "1.4", method: "41.5 减 40.1",
    operands: [{ ordinal: 1, quote: "close 41.5" }, { ordinal: 2, quote: "previous close 40.1" }] }),
    "由 [1]「close 41.5」 与 [2]「previous close 40.1」 计算，已自动复算，请自行判断");
  assert.equal(evidenceText({ kind: "conflict", figure: "8.5%", ordinal: 1, quote: "grew 6.2%" }),
    "来源 [1] 对同一个量写作「grew 6.2%」，与这句不一致，请自行判断");
  assert.equal(evidenceText({ kind: "unknown", figure: "1" }), null);
  for (const evidence of [{ kind: "found", figure: "1", ordinal: 1, quote: "x", read_as: "1" }, { kind: "conflict", figure: "1", ordinal: 1, quote: "x" }]) {
    assert.ok(!evidenceText(evidence).includes("已核实"));
  }
});

test("a partly read line keeps its flag and shows the evidence beside it", () => {
  const item = { line: "营收增长 8.5%，利率下调 0.5% [1]。", reason: "unsupported_numeric_claim", numbers: ["8.5%"],
    evidence: [{ kind: "found", figure: "0.5%", ordinal: 1, quote: "half a percentage point", read_as: "0.5%" }] };
  const marked = markUnverified(item.line, [item], labels);
  assert.ok(marked.includes("[证据不足：原因:unsupported_numeric_claim](#unverified-0)"));
  assert.ok(marked.includes("[数字未核实：8.5%](#unverified-num-0)"));
  assert.ok(marked.includes("(#unverified-ev-0)"));
});

test("evidence survives normalisation only when it is well formed, and its flag links parse", () => {
  const [kept] = normalizeUnverified([{ line: "有效 [1]", reason: "x", evidence: [
    { kind: "found", figure: "0.5%", ordinal: 1, quote: "q", read_as: "0.5%" }, { kind: "bogus", figure: "1" }, null, { kind: "conflict" },
  ] }]);
  assert.equal(kept.evidence.length, 1);
  assert.equal(kept.evidence[0].kind, "found");
  assert.deepEqual(parseFlagHref("#unverified-ev-3"), { kind: "evidence", index: 3 });
  assert.deepEqual(parseFlagHref("#unverified-3"), { kind: "insufficient", index: 3 });
});
