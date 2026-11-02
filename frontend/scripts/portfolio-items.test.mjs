import assert from "node:assert/strict";
import test from "node:test";
import { ENTRY_KINDS, blankEntry, entryBody, entryLine, formatMoney, formatPercent, formatPrice, formatShares, parseAmount, planBody, planChanged, planForm, pnlTone, warningLabels } from "../src/portfolio-items.mjs";

test("money: two places, thousands separators, a sign only where asked, a dash when unknown", () => {
  assert.equal(formatMoney("1999"), "1,999.00");
  assert.equal(formatMoney("798.6"), "798.60");
  assert.equal(formatMoney("-1234567.891"), "-1,234,567.89");
  assert.equal(formatMoney("598.80", { signed: true }), "+598.80");
  assert.equal(formatMoney("-120", { signed: true }), "-120.00");
  assert.equal(formatMoney("0.00", { signed: true }), "0.00");
  assert.equal(formatMoney("-0.001"), "0.00");
  assert.equal(formatMoney(10000), "10,000.00");
  assert.equal(formatMoney("1.005"), "1.01");
  assert.equal(formatMoney("9.999"), "10.00");
  for (const blank of [null, undefined, "", "abc", NaN]) assert.equal(formatMoney(blank), "—");
  assert.equal(formatMoney(null, { dash: "暂无" }), "暂无");
});

test("percent: a number of percent with its sign and symbol", () => {
  assert.equal(formatPercent("27.5"), "27.50%");
  assert.equal(formatPercent("54.5454"), "54.55%");
  assert.equal(formatPercent("-3", { signed: true }), "-3.00%");
  assert.equal(formatPercent("12", { signed: true }), "+12.00%");
  assert.equal(formatPercent(null), "—");
});

test("shares keep their own places; prices show at least two", () => {
  assert.equal(formatShares("60"), "60");
  assert.equal(formatShares("1000.50000000"), "1,000.5");
  assert.equal(formatShares(null), "—");
  assert.equal(formatPrice("80.0100"), "80.01");
  assert.equal(formatPrice("90"), "90.00");
  assert.equal(formatPrice("66.7000"), "66.70");
  assert.equal(formatPrice("12.34567"), "12.34567");
});

test("tone follows the sign and is separate from the text", () => {
  assert.deepEqual(["599.4", "-1", "0.00", "-0.001", null].map(pnlTone), ["gain", "loss", "flat", "flat", "none"]);
});

test("typed amounts: commas allowed, signs and junk refused", () => {
  assert.equal(parseAmount("1,999.5"), "1999.5");
  assert.equal(parseAmount(" 80 "), "80");
  for (const bad of ["", "abc", "1e3", "-5", "1.2.3", "$5"]) assert.equal(parseAmount(bad), null);
  assert.equal(parseAmount("-5", { allowNegative: true }), "-5");
});

test("the add-entry form becomes a request body, or says what is wrong", () => {
  const form = { ...blankEntry("buy"), symbol: " intc ", quantity: "100", price: "80", fee: "1", occurred_on: "2026-10-01" };
  assert.deepEqual(entryBody(form), { body: { kind: "buy", symbol: "INTC", quantity: "100", price: "80", fee: "1", occurred_on: "2026-10-01" } });
  assert.match(entryBody({ ...form, symbol: "??" }).error, /美股代码/);
  assert.match(entryBody({ ...form, quantity: "0" }).error, /股数/);
  assert.match(entryBody({ ...form, price: "" }).error, /成交价/);
  assert.match(entryBody({ ...form, kind: "opening", price: "" }).error, /平均成本/);
  assert.match(entryBody({ ...form, fee: "x" }).error, /手续费/);
  assert.deepEqual(entryBody({ ...blankEntry("split"), symbol: "NVDA", ratio: "10" }).body, { kind: "split", symbol: "NVDA", ratio: "10" });
  assert.match(entryBody({ ...blankEntry("split"), symbol: "NVDA", ratio: "1" }).error, /拆股比例/);
  assert.deepEqual(entryBody({ ...blankEntry("deposit"), amount: "10,000" }).body, { kind: "deposit", amount: "10000" });
  assert.match(entryBody({ ...blankEntry("withdraw"), amount: "-5" }).error, /金额/);
  assert.deepEqual(entryBody({ ...blankEntry("dividend"), symbol: "AAPL", amount: "12.5" }).body, { kind: "dividend", symbol: "AAPL", amount: "12.5" });
  assert.ok(ENTRY_KINDS.includes("opening") && !ENTRY_KINDS.includes("cash_adjust"));
});

test("a ledger row reads as one line", () => {
  assert.equal(entryLine({ kind: "buy", quantity: "100", price: "80.0000", fee: "1.00" }), "买入 100 @ 80.00 · 手续费 1.00");
  assert.equal(entryLine({ kind: "sell", quantity: "40", price: "100", fee: null }), "卖出 40 @ 100.00");
  assert.equal(entryLine({ kind: "split", ratio: "2" }), "拆股 1 拆 2");
  assert.equal(entryLine({ kind: "cash_adjust", amount: "-500" }), "资金调整 -500.00");
  assert.equal(entryLine({ kind: "deposit", amount: "10000" }), "入金 10,000.00");
});

test("the plan form round-trips; a blank price is cleared, junk is refused", () => {
  const plan = { plan_text: "跌到 70 补", add_price: "70.0000", stop_price: null, target_price: "100.5000" };
  const form = planForm(plan);
  assert.deepEqual(form, { plan_text: "跌到 70 补", add_price: "70.00", stop_price: "", target_price: "100.50" });
  assert.equal(planChanged(plan, form), false);
  assert.equal(planChanged(plan, { ...form, stop_price: "60" }), true);
  assert.deepEqual(planBody(form), { body: { plan_text: "跌到 70 补", add_price: "70.00", stop_price: null, target_price: "100.50" } });
  assert.match(planBody({ ...form, add_price: "abc" }).error, /价格/);
});

test("warnings read as sentences; unknown codes are dropped", () => {
  assert.deepEqual(warningLabels(["available_funds_negative", "x"]).length, 1);
  assert.deepEqual(warningLabels(undefined), []);
});
