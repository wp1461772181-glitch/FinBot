// The price lines of an alert task as the form holds them: one row per line, "code + above / below + price".  Pure, so a node test holds it.
//
// What goes to the server is what it always was: `config.price_lines`, a list of {symbol, above} / {symbol, below} (inbox-items.mjs `parsePriceLines` made it
// from the typed text "NVDA>150, AAPL<180").  The rows are another way to write the same list: the grammar of one line, the separators between lines, the upper
// casing of the code and the numbers that come out are the old parser's, so the body of a save is the same for the same lines.  What the old text could not
// say (>=, a minus, an exponent, a code that is not a code) is still not a line: it stays in its row as typed, marked, and the save waits for the reader to
// fix or delete it.  Nothing is dropped quietly.

const PART_SPLIT = /[,，;；\n]+/;
const PART = /^([A-Za-z][A-Za-z0-9.\-]{0,9})\s*([<>])\s*(\d+(?:\.\d+)?)$/;
const CODE = /^[A-Za-z][A-Za-z0-9.\-]{0,9}$/;
const NUMBER = /^\d+(?:\.\d+)?$/;

export const PRICE_SIDES = ["above", "below"];

/** A row nobody has typed in yet: the code empty, 高于 chosen. */
export function blankRow() { return { symbol: "", side: "above", price: "" }; }

/** A piece of stored or typed text that is not a line: kept as it was, shown in its row, never sent. */
export function isRawRow(row) { return typeof row?.raw === "string"; }

const isBlankRow = (row) => (isRawRow(row) ? !row.raw.trim() : !String(row?.symbol ?? "").trim() && !String(row?.price ?? "").trim());

/** A stored number as the text a reader would type: 150, 150.5, 0.0000001 (never an exponent). */
export function plainNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "");
  const text = String(number);
  if (!/e/i.test(text)) return text;
  return number.toFixed(12).replace(/0+$/, "").replace(/\.$/, "");
}

/** The text "NVDA>150, AAPL<180" as rows; a part that is not a line becomes a raw row with the part as written. */
export function parsePriceText(text) {
  return String(text ?? "").split(PART_SPLIT).map((part) => part.trim()).filter(Boolean).map((part) => {
    const match = PART.exec(part);
    return match ? { symbol: match[1].toUpperCase(), side: match[2] === ">" ? "above" : "below", price: match[3] } : { raw: part };
  });
}

/** A task's stored price lines as rows.  The usual value is a list of {symbol, above?, below?} (a line with both sides is two rows, above first);
 *  an old task may hold the typed text itself; anything else readable at all becomes a raw row, never nothing. */
export function linesToRows(lines) {
  if (typeof lines === "string") return parsePriceText(lines);
  if (!Array.isArray(lines)) return [];
  return lines.flatMap((line) => {
    if (typeof line === "string") return parsePriceText(line);
    const sides = line && typeof line === "object" ? PRICE_SIDES.filter((side) => line[side] != null) : [];
    if (!sides.length || !String(line.symbol ?? "").trim()) return [{ raw: JSON.stringify(line ?? null) }];
    return sides.map((side) => ({ symbol: String(line.symbol), side, price: plainNumber(line[side]) }));
  });
}

/** What is wrong with one row: null, "raw" (not a line), "symbol", "price", or "incomplete" (one of the two empty).  A row with both empty is not wrong, it is nothing. */
export function rowProblem(row) {
  if (isBlankRow(row)) return null;
  if (isRawRow(row)) return "raw";
  const symbol = String(row.symbol ?? "").trim(), price = String(row.price ?? "").trim();
  if (!symbol || !price) return "incomplete";
  if (!CODE.test(symbol)) return "symbol";
  if (!NUMBER.test(price)) return "price";
  return null;
}

/** The problems of a list of rows: [{ index, problem }] in row order. */
export function rowsProblems(rows) {
  return (Array.isArray(rows) ? rows : []).flatMap((row, index) => { const problem = rowProblem(row); return problem ? [{ index, problem }] : []; });
}

/** The list the server takes, or null while a row is wrong.  Empty rows are skipped; the keys come out in the old order (symbol, then the side). */
export function rowsToLines(rows) {
  const list = Array.isArray(rows) ? rows : [];
  if (rowsProblems(list).length) return null;
  return list.filter((row) => !isBlankRow(row)).map((row) => ({ symbol: row.symbol.trim().toUpperCase(), [row.side === "below" ? "below" : "above"]: Number(row.price.trim()) }));
}

/** The old text of the rows ("NVDA>150, AAPL<180"); a raw row keeps its text. */
export function rowsToText(rows) {
  return (Array.isArray(rows) ? rows : []).filter((row) => !isBlankRow(row)).map((row) => isRawRow(row) ? row.raw : `${String(row.symbol).trim().toUpperCase()}${row.side === "below" ? "<" : ">"}${String(row.price).trim()}`).join(", ");
}

/** True when two lists of rows say the same thing (a row's code case and spaces do not count). */
export function sameRows(a, b) {
  return rowsToText(a) === rowsToText(b);
}
