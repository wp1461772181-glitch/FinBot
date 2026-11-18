import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { formatPriceLines, parsePriceLines } from "../src/inbox-items.mjs";
import { blankRow, linesToRows, parsePriceText, plainNumber, rowProblem, rowsProblems, rowsToLines, rowsToText, sameRows } from "../src/price-lines.mjs";

// What the old 任务 form did with the typed price-line text, recorded from the old UI (tools/shots/fixtures/routine-bodies-baseline.json): which texts it took and what it sent.
const baseline = JSON.parse(readFileSync(new URL("../tools/shots/fixtures/routine-bodies-baseline.json", import.meta.url), "utf8"));
const TEXTS = Object.entries(baseline.priceText).map(([key, value]) => [JSON.parse(key), value]);

test("every text the old form was tried with: the rows take it or refuse it as the old form did, and the lines they make are the ones it sent", () => {
  assert.ok(TEXTS.length >= 40);
  for (const [text, old] of TEXTS) {
    if (text.includes("\n")) continue; // a single-line input swallows the newline in the browser (see the delivery note); the function-level check below covers it
    const rows = parsePriceText(text);
    const lines = rowsToLines(rows);
    assert.equal(lines !== null, old.accepted, `accepted: ${JSON.stringify(text)}`);
    if (old.accepted) assert.equal(JSON.stringify(lines), JSON.stringify(old.price_lines), `lines: ${JSON.stringify(text)}`);
  }
});

test("on every text the rows agree with the old parser (parsePriceLines), newline separators included", () => {
  const extra = ["NVDA>150\nAAPL<180", "NVDA>150\n\n AAPL < 180.25 ;; tsla>1", "nvda<0.5，BRK.B>450", "ABCDEFGHIJK>1"];
  for (const text of [...TEXTS.map(([t]) => t), ...extra]) {
    const old = parsePriceLines(text);
    const lines = rowsToLines(parsePriceText(text));
    assert.equal(JSON.stringify(lines), JSON.stringify(old), `text: ${JSON.stringify(text)}`);
  }
});

test("stored lines become rows (a line with both sides is two rows, above first) and back to the same lines the old form saved", () => {
  const stored = [{ symbol: "NVDA", above: 140 }, { symbol: "AAPL", below: 190 }, { symbol: "TSLA", above: 300, below: 120.5 }];
  const rows = linesToRows(stored);
  assert.deepEqual(rows, [
    { symbol: "NVDA", side: "above", price: "140" }, { symbol: "AAPL", side: "below", price: "190" },
    { symbol: "TSLA", side: "above", price: "300" }, { symbol: "TSLA", side: "below", price: "120.5" },
  ]);
  // The old form's own round trip: formatPriceLines, then parsePriceLines.
  assert.equal(JSON.stringify(rowsToLines(rows)), JSON.stringify(parsePriceLines(formatPriceLines(stored))));
  assert.equal(rowsToText(rows), formatPriceLines(stored));
});

test("the round trip is stable: rows → lines → rows → lines, and rows → text → rows", () => {
  const rows = parsePriceText("NVDA>150, aapl < 180.5; TSLA>0.0000001");
  const lines = rowsToLines(rows);
  assert.deepEqual(linesToRows(lines), parsePriceText(rowsToText(rows)));
  assert.equal(JSON.stringify(rowsToLines(linesToRows(lines))), JSON.stringify(lines));
  assert.equal(JSON.stringify(rowsToLines(parsePriceText(rowsToText(rows)))), JSON.stringify(lines));
  assert.ok(sameRows(rows, parsePriceText("nvda>150,AAPL<180.5,tsla>0.0000001")));
});

test("a stored number is written the way it was typed, never with an exponent", () => {
  assert.equal(plainNumber(150), "150");
  assert.equal(plainNumber(150.5), "150.5");
  assert.equal(plainNumber(1e-7), "0.0000001");
  assert.equal(plainNumber(99999999), "99999999");
  assert.deepEqual(linesToRows([{ symbol: "ABC", below: 1e-7 }]), [{ symbol: "ABC", side: "below", price: "0.0000001" }]);
  assert.equal(JSON.stringify(rowsToLines(linesToRows([{ symbol: "ABC", below: 1e-7 }]))), '[{"symbol":"ABC","below":1e-7}]');
});

test("what the old text could not say stays in its row as written, marked, and is never sent or dropped", () => {
  for (const text of ["NVDA>=150", "NVDA>-5", "NVDA>1e3", "腾讯>300", "ABCDEFGHIJK>1"]) {
    const rows = parsePriceText(text);
    assert.deepEqual(rows, [{ raw: text }]);
    assert.equal(rowProblem(rows[0]), "raw");
    assert.equal(rowsToLines(rows), null);
    assert.equal(rowsToText(rows), text);
  }
  // a comma inside a number splits it, as it did in the old parser: "NVDA>1,000" is the line NVDA>1 and the piece "000"
  assert.deepEqual(parsePriceText("NVDA>1,000"), [{ symbol: "NVDA", side: "above", price: "1" }, { raw: "000" }]);
  const mixed = parsePriceText("nvda > 150.5; AAPL<180, 腾讯>300");
  assert.deepEqual(mixed, [{ symbol: "NVDA", side: "above", price: "150.5" }, { symbol: "AAPL", side: "below", price: "180" }, { raw: "腾讯>300" }]);
  assert.deepEqual(rowsProblems(mixed), [{ index: 2, problem: "raw" }]);
  assert.equal(rowsToLines(mixed), null);
});

test("an old task that holds the typed text itself (not a list) opens as rows, the unreadable part kept; other shapes are kept, not lost", () => {
  assert.deepEqual(linesToRows("nvda > 150.5; AAPL<180, 腾讯>300"), parsePriceText("nvda > 150.5; AAPL<180, 腾讯>300"));
  assert.deepEqual(linesToRows(["NVDA>150", { symbol: "AAPL", below: 180 }]), [{ symbol: "NVDA", side: "above", price: "150" }, { symbol: "AAPL", side: "below", price: "180" }]);
  assert.deepEqual(linesToRows([{ symbol: "AAPL" }, null, 5]).map((row) => "raw" in row), [true, true, true]);
  assert.deepEqual(linesToRows([{ symbol: "AAPL" }]), [{ raw: '{"symbol":"AAPL"}' }]);
  assert.deepEqual(linesToRows(undefined), []);
  assert.deepEqual(linesToRows(null), []);
  assert.deepEqual(linesToRows([]), []);
});

test("a row is judged on its own: both empty is nothing, one empty is incomplete, then the code, then the price", () => {
  assert.equal(rowProblem(blankRow()), null);
  assert.equal(rowProblem({ symbol: "NVDA", side: "above", price: "" }), "incomplete");
  assert.equal(rowProblem({ symbol: "", side: "below", price: "5" }), "incomplete");
  assert.equal(rowProblem({ symbol: "1A", side: "above", price: "5" }), "symbol");
  assert.equal(rowProblem({ symbol: "NVDA", side: "above", price: "-5" }), "price");
  assert.equal(rowProblem({ symbol: "NVDA", side: "above", price: "5." }), "price");
  assert.equal(rowProblem({ symbol: " nvda ", side: "above", price: " 5 " }), null);
  assert.equal(rowProblem({ raw: "   " }), null); // a raw row the reader emptied is nothing
  assert.equal(rowProblem({ raw: "x" }), "raw");
});

test("empty rows are skipped, the code is upper-cased and trimmed, the side picks the key, the keys come in the old order", () => {
  const rows = [{ symbol: " nvda ", side: "above", price: " 150 " }, blankRow(), { symbol: "aapl", side: "below", price: "180.50" }, { raw: "" }];
  assert.equal(JSON.stringify(rowsToLines(rows)), '[{"symbol":"NVDA","above":150},{"symbol":"AAPL","below":180.5}]');
  assert.equal(JSON.stringify(rowsToLines([])), "[]");
  assert.equal(rowsToText(rows), "NVDA>150, AAPL<180.50");
});
