// What the 持仓 page shows of a figure, kept apart so a node test reads it.  Nothing here computes money: every number is a string the
// server sent, shown through the formatters of portfolio-items.mjs (the one place that knows how the ledger's figures are written).
import { KIND_LABELS, formatMoney, formatPercent, formatPrice, formatShares, pnlTone, planChanged, planForm } from "../../portfolio-items.mjs";

const DIRECTION = { gain: "up", loss: "down", flat: "flat", none: "none" };

/**
 * How a profit-and-loss figure is drawn.  `direction` is "up" or "down" for a figure with a sign: then it gets the up / down colour, an arrow and
 * the sign, all three.  A zero ("flat") and a figure we do not have ("none") are plain text: no colour, no arrow, no sign.
 */
export function pnlView(value, { percent = false } = {}) {
  const direction = DIRECTION[pnlTone(value)];
  const text = percent ? formatPercent(value, { signed: true }) : formatMoney(value, { signed: true });
  return { direction, text, signed: direction === "up" || direction === "down" };
}

const TRADE = new Set(["opening", "buy", "sell"]);

/**
 * One ledger row as the cells of a table: the type's label (a phrase key), the quantity (shares, or the split's ratio), the price (a trade's price;
 * for a dividend or a cash row it is the amount) and the fee (trades only, and only when there is one).
 */
export function ledgerCells(tx) {
  const label = KIND_LABELS[tx.kind] ?? tx.kind;
  if (TRADE.has(tx.kind)) return { label, quantity: formatShares(tx.quantity), price: formatPrice(tx.price), fee: tx.fee ? formatMoney(tx.fee) : null };
  if (tx.kind === "split") return { label, quantity: `1 : ${formatShares(tx.ratio)}`, price: null, fee: null };
  return { label, quantity: null, price: formatMoney(tx.amount, { signed: tx.kind === "cash_adjust" }), fee: null };
}

/** The records of one symbol, in the order the server sent them. */
export const recordsOf = (transactions, symbol) => (Array.isArray(transactions) ? transactions : []).filter((tx) => tx.symbol === symbol);

/** The plan form of a position: the reader's unsaved draft when there is one, else the saved plan; and whether it differs from what is saved. */
export function planDraft(plan, draft) {
  const form = draft ?? planForm(plan);
  return { form, changed: Boolean(draft) && planChanged(plan, form) };
}
