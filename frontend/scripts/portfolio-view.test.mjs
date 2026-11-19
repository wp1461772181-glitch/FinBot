import assert from "node:assert/strict";
import test from "node:test";
import { ledgerCells, planDraft, pnlView, recordsOf } from "../src/app/portfolio/portfolio-view.mjs";

test("a gain and a loss carry a direction and a sign; a zero and a missing figure carry neither", () => {
  assert.deepEqual(pnlView("4221.00"), { direction: "up", text: "+4,221.00", signed: true });
  assert.deepEqual(pnlView("-1800.80"), { direction: "down", text: "-1,800.80", signed: true });
  assert.deepEqual(pnlView("0.00"), { direction: "flat", text: "0.00", signed: false });
  assert.deepEqual(pnlView("0.004"), { direction: "flat", text: "0.00", signed: false });
  assert.deepEqual(pnlView(null), { direction: "none", text: "—", signed: false });
  assert.deepEqual(pnlView(""), { direction: "none", text: "—", signed: false });
  assert.deepEqual(pnlView("garbage"), { direction: "none", text: "—", signed: false });
});

test("a percentage is signed the same way, and rounds to zero the same way", () => {
  assert.deepEqual(pnlView("14.94", { percent: true }), { direction: "up", text: "+14.94%", signed: true });
  assert.deepEqual(pnlView("-17.65", { percent: true }), { direction: "down", text: "-17.65%", signed: true });
  assert.deepEqual(pnlView("0.001", { percent: true }), { direction: "flat", text: "0.00%", signed: false });
  assert.equal(pnlView(undefined, { percent: true }).text, "—");
});

test("a ledger row becomes the cells of its kind", () => {
  assert.deepEqual(ledgerCells({ kind: "buy", quantity: "100", price: "182", fee: "1.00" }), { label: "买入", quantity: "100", price: "182.00", fee: "1.00" });
  assert.deepEqual(ledgerCells({ kind: "sell", quantity: "20.5", price: "270.6", fee: null }), { label: "卖出", quantity: "20.5", price: "270.60", fee: null });
  assert.deepEqual(ledgerCells({ kind: "opening", quantity: "30", price: "168.1234", fee: "0" }), { label: "期初持仓", quantity: "30", price: "168.1234", fee: "0.00" });
  assert.deepEqual(ledgerCells({ kind: "dividend", amount: "36" }), { label: "分红", quantity: null, price: "36.00", fee: null });
  assert.deepEqual(ledgerCells({ kind: "split", ratio: "2" }), { label: "拆股", quantity: "1 : 2", price: null, fee: null });
  assert.deepEqual(ledgerCells({ kind: "deposit", amount: "5000" }), { label: "入金", quantity: null, price: "5,000.00", fee: null });
  assert.deepEqual(ledgerCells({ kind: "cash_adjust", amount: "-12.5" }), { label: "资金调整", quantity: null, price: "-12.50", fee: null });
  assert.equal(ledgerCells({ kind: "something_new" }).label, "something_new");
});

test("the records of one symbol keep the server's order and ignore the others", () => {
  const all = [{ id: 1, symbol: "AAPL" }, { id: 2, symbol: "" }, { id: 3, symbol: "NVDA" }, { id: 4, symbol: "AAPL" }];
  assert.deepEqual(recordsOf(all, "AAPL").map((r) => r.id), [1, 4]);
  assert.deepEqual(recordsOf(null, "AAPL"), []);
});

test("a plan form is the draft when there is one, and is changed only when the draft differs from what is saved", () => {
  const plan = { plan_text: "等回踩", add_price: "200.00", stop_price: null, target_price: "235.00" };
  const saved = planDraft(plan, undefined);
  assert.deepEqual(saved, { form: { plan_text: "等回踩", add_price: "200.00", stop_price: "", target_price: "235.00" }, changed: false });
  assert.equal(planDraft(plan, { ...saved.form }).changed, false);
  assert.equal(planDraft(plan, { ...saved.form, stop_price: "180" }).changed, true);
  assert.equal(planDraft(plan, { ...saved.form, plan_text: "  等回踩  " }).changed, false);
  assert.equal(planDraft(undefined, { plan_text: "x", add_price: "", stop_price: "", target_price: "" }).changed, true);
});
