import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PUBLIC_MARK_ARIA,
  PUBLIC_MARK_GLYPH,
  PUBLIC_MARK_LABELS,
  attachPublicMarks,
  normalizePublicMarks,
  parsePublicMarkHref,
  publicMarkOrdinal,
  publicMarkQuoteText,
} from "../src/chat-public-marks.mjs";

// The shape the server sends (chat history `public_marks`), built the way public_view() builds it.
function mark(id, sentence, overrides = {}) {
  return {
    id,
    sentence_idx: 0,
    marker: "neutral",
    hit_kind: "number",
    template: "来源 [1] 中同一指标的数值与此句不同",
    hover: {
      answer_sentence: sentence,
      evidence: { ordinal: 1, quote: "Holder A removed 21,071,170 shares", completeness: "complete" },
    },
    ...overrides,
  };
}

const FORBIDDEN = ["矛盾", "编造", "已核验", "核实", "证据不足", "数字未核实"];

test("normalize keeps well-formed marks in server order and drops anything else", () => {
  const views = normalizePublicMarks([mark("a", "甲句子一二三"), null, "text", { marker: "red" }, mark("b", "乙句子一二三")]);
  assert.deepEqual(views.map((v) => v.id), ["a", "b"]);
  assert.deepEqual(normalizePublicMarks(undefined), []);
});

test("a marker is appended to the line that holds the sentence, and the sentence text is otherwise unchanged", () => {
  const content = "第一段第一句话很长很长。\n第二段的 Northwind 第三季度营收下降 8% [1]。\n第三段";
  const out = attachPublicMarks(content, [mark("a", "Northwind 第三季度营收下降 8% [1]")]);
  const lines = out.split("\n");
  assert.equal(lines[0], content.split("\n")[0]);
  assert.equal(lines[2], "第三段");
  assert.equal(lines[1], `${content.split("\n")[1]} [${PUBLIC_MARK_GLYPH}](#public-mark-0)`);
  assert.equal(out.replace(/ \[◦\]\(#public-mark-\d+\)/g, ""), content);
});

test("a sentence matched without its markers and whitespace", () => {
  const out = attachPublicMarks("Northwind 营收 下降 8%[1]。", [mark("a", "Northwind 营收下降 8% [1]")]);
  assert.match(out, /\(#public-mark-0\)$/);
});

test("two marks on one line get two links in server order", () => {
  const out = attachPublicMarks("甲句子一二三。乙句子一二三。", [mark("a", "甲句子一二三"), mark("b", "乙句子一二三")]);
  assert.equal(out, `甲句子一二三。乙句子一二三。 [${PUBLIC_MARK_GLYPH}](#public-mark-0) [${PUBLIC_MARK_GLYPH}](#public-mark-1)`);
});

test("a table row keeps its closing bar", () => {
  const out = attachPublicMarks("| 指标 | 说明 |\n| 营收 | 第三季度营收下降 8% |", [mark("a", "第三季度营收下降 8%")]);
  assert.equal(out.split("\n")[0], `| 指标 | 说明 |`);
  assert.equal(out.split("\n")[1], `| 营收 | 第三季度营收下降 8% [${PUBLIC_MARK_GLYPH}](#public-mark-0) |`);
});

test("a mark whose sentence is not in the text is not placed, and a very short key is not placed", () => {
  const content = "完全不同的一段文字。";
  assert.equal(attachPublicMarks(content, [mark("a", "别处的句子内容")]), content);
  assert.equal(attachPublicMarks("营收增长。", [mark("a", "营收")]), "营收增长。");
  assert.equal(attachPublicMarks(content, []), content);
  assert.equal(attachPublicMarks(undefined, [mark("a", "x")]), "");
});

test("the link target indexes the normalized list, so unplaced marks keep their own index", () => {
  const out = attachPublicMarks("第二句的内容在这里。", [mark("a", "别处的句子内容"), mark("b", "第二句的内容在这里")]);
  assert.equal(out, `第二句的内容在这里。 [${PUBLIC_MARK_GLYPH}](#public-mark-1)`);
});

test("parsePublicMarkHref accepts only the marker links", () => {
  assert.equal(parsePublicMarkHref("#public-mark-3"), 3);
  assert.equal(parsePublicMarkHref("#citation-3"), null);
  assert.equal(parsePublicMarkHref("#unverified-3"), null);
  assert.equal(parsePublicMarkHref("#public-mark-x"), null);
  assert.equal(parsePublicMarkHref(undefined), null);
});

test("the quote line shows the verbatim quote, marks excerpts, and tolerates a missing ordinal", () => {
  const [view] = normalizePublicMarks([mark("a", "甲句子一二三")]);
  assert.equal(publicMarkQuoteText(view), "来源 [1] 原文：「Holder A removed 21,071,170 shares」");
  const [excerpt] = normalizePublicMarks([mark("b", "甲句子一二三", { hover: { answer_sentence: "甲句子一二三", evidence: { ordinal: 2, quote: "q", completeness: "excerpt" } } })]);
  assert.equal(publicMarkQuoteText(excerpt), "来源 [2] 原文（节录）：「q」");
  assert.equal(publicMarkOrdinal(excerpt), 2);
  const [bare] = normalizePublicMarks([mark("c", "甲句子一二三", { hover: { answer_sentence: "甲句子一二三", evidence: { ordinal: null, quote: "q", completeness: "complete" } } })]);
  assert.equal(publicMarkQuoteText(bare), "来源原文：「q」");
  assert.equal(publicMarkOrdinal(bare), null);
});

test("the translator is applied to the fixed labels only", () => {
  const [view] = normalizePublicMarks([mark("a", "甲句子一二三")]);
  const seen = [];
  const text = publicMarkQuoteText(view, (s) => { seen.push(s); return s; });
  assert.ok(seen.includes(PUBLIC_MARK_LABELS.quote));
  assert.ok(text.includes("Holder A removed"));
});

test("a reason field from the judge never reaches the placed text", () => {
  const leaked = { ...mark("a", "甲句子一二三"), reason: "REASON-SECRET" };
  const out = attachPublicMarks("甲句子一二三。", [leaked]);
  assert.ok(!out.includes("REASON-SECRET"));
  const [view] = normalizePublicMarks([leaked]);
  assert.ok(!JSON.stringify(view).includes("REASON-SECRET"));
});

test("every UI literal and the glyph avoid the forbidden public words", () => {
  const literals = [PUBLIC_MARK_GLYPH, PUBLIC_MARK_ARIA, ...Object.values(PUBLIC_MARK_LABELS)];
  for (const text of literals) for (const word of FORBIDDEN) assert.ok(!text.includes(word), `${word} in ${text}`);
  const [view] = normalizePublicMarks([mark("a", "甲句子一二三")]);
  const rendered = [publicMarkQuoteText(view), attachPublicMarks("甲句子一二三。", [mark("a", "甲句子一二三")])];
  for (const text of rendered) for (const word of FORBIDDEN) assert.ok(!text.includes(word), `${word} in ${text}`);
});
