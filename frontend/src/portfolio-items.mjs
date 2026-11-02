// Pure helpers of the 持仓 page and the 我的持仓 workspace card (personal finance assistant, Task 6), kept apart so
// node tests read them.  The server sends money as plain decimal strings ("1999.00"); they are formatted here as
// strings, never through a float, so a figure on screen is the figure the ledger holds.

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;
const group = (digits) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

function parts(value) {
  if (value === null || value === undefined || value === "") return null;
  const text = typeof value === "number" ? (Number.isFinite(value) ? String(value) : "") : String(value).trim().replace(/,/g, "");
  const match = DECIMAL.exec(text);
  if (match) return { negative: match[1] === "-", whole: match[2], fraction: match[3] ?? "" };
  const number = Number(text);
  if (!text || !Number.isFinite(number)) return null;
  return parts(number.toFixed(8));
}

function fixed(value, places) {
  const p = parts(value);
  if (!p) return null;
  if (p.fraction.length <= places) return { ...p, fraction: p.fraction.padEnd(places, "0") };
  // Round half up on the decimal digits (the server already sends 2 places for money; this is for the odd longer value).
  const digits = BigInt(p.whole + p.fraction.slice(0, places)) + (p.fraction.charCodeAt(places) >= 53 ? 1n : 0n);
  const raw = digits.toString().padStart(places + 1, "0");
  return { negative: p.negative, whole: raw.slice(0, raw.length - places), fraction: raw.slice(raw.length - places) };
}

/** "1999" → "1,999.00"; null/blank/garbage → the dash.  `signed` puts + on gains (a zero has no sign). */
export function formatMoney(value, { signed = false, places = 2, dash = "—" } = {}) {
  const p = fixed(value, places);
  if (!p) return dash;
  const zero = /^0*$/.test(p.whole + p.fraction);
  const sign = zero ? "" : p.negative ? "-" : signed ? "+" : "";
  return `${sign}${group(p.whole)}${places ? "." + p.fraction : ""}`;
}

/** A percentage given as a number of percent ("27.5" → "27.50%"); the dash when it is unknown. */
export function formatPercent(value, { signed = false, places = 2, dash = "—" } = {}) {
  const text = formatMoney(value, { signed, places, dash: "" });
  return text ? `${text}%` : dash;
}

/** Shares keep the places they have ("60", "1,000.5"), never padded. */
export function formatShares(value) {
  const p = parts(value);
  if (!p) return "—";
  const fraction = p.fraction.replace(/0+$/, "");
  return `${p.negative ? "-" : ""}${group(p.whole)}${fraction ? "." + fraction : ""}`;
}

/** A price at its own precision, at least 2 places ("80.0100" → "80.01", "90" → "90.00"). */
export function formatPrice(value) {
  const p = parts(value);
  if (!p) return "—";
  const fraction = p.fraction.replace(/0+$/, "").padEnd(2, "0");
  return `${p.negative ? "-" : ""}${group(p.whole)}.${fraction}`;
}

/** "gain" | "loss" | "flat" | "none": for a class name only; the sign is always in the text too. */
export function pnlTone(value) {
  const p = fixed(value, 2);
  if (!p) return "none";
  if (/^0*$/.test(p.whole + p.fraction)) return "flat";
  return p.negative ? "loss" : "gain";
}

/** What a typed amount means as a decimal string, or null ("1,999.5" → "1999.5"; "abc", "1e3", "-" → null). */
export function parseAmount(text, { allowNegative = false } = {}) {
  const clean = String(text ?? "").trim().replace(/,/g, "");
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(clean);
  if (!match || (match[1] && !allowNegative)) return null;
  return clean;
}

export const KIND_LABELS = {
  opening: "期初持仓", buy: "买入", sell: "卖出", dividend: "分红", split: "拆股",
  deposit: "入金", withdraw: "出金", cash_adjust: "资金调整",
};
export const ENTRY_KINDS = ["buy", "sell", "opening", "dividend", "split", "deposit", "withdraw"];
const TRADE = new Set(["opening", "buy", "sell"]);
const CASH = new Set(["deposit", "withdraw", "cash_adjust"]);
const TICKER = /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/;

export const blankEntry = (kind = "buy") => ({ kind, symbol: "", quantity: "", price: "", fee: "", amount: "", ratio: "", occurred_on: "", note: "" });

/** The request body of the add-entry form, or `{ error }` (a phrase the page translates) before anything is sent. */
export function entryBody(form) {
  const kind = form?.kind;
  if (!KIND_LABELS[kind]) return { error: "请选择记录类型。" };
  const body = { kind };
  if (!CASH.has(kind)) {
    const symbol = String(form.symbol ?? "").trim().toUpperCase();
    if (!TICKER.test(symbol)) return { error: "请输入有效的美股代码，例如 INTC 或 BRK.B。" };
    body.symbol = symbol;
  }
  if (TRADE.has(kind)) {
    const quantity = parseAmount(form.quantity), price = parseAmount(form.price);
    if (!quantity || Number(quantity) <= 0) return { error: "股数要大于 0。" };
    if (!price || Number(price) <= 0) return { error: kind === "opening" ? "请填平均成本（每股）。" : "成交价要大于 0。" };
    body.quantity = quantity; body.price = price;
    if (String(form.fee ?? "").trim()) {
      const fee = parseAmount(form.fee);
      if (fee === null) return { error: "手续费要填不小于 0 的数字。" };
      body.fee = fee;
    }
  } else if (kind === "split") {
    const ratio = parseAmount(form.ratio);
    if (!ratio || Number(ratio) <= 0 || Number(ratio) === 1) return { error: "拆股比例要大于 0 且不等于 1（1 拆 2 填 2）。" };
    body.ratio = ratio;
  } else {
    const amount = parseAmount(form.amount);
    if (!amount || Number(amount) <= 0) return { error: "金额要大于 0。" };
    body.amount = amount;
  }
  if (String(form.occurred_on ?? "").trim()) body.occurred_on = String(form.occurred_on).trim();
  if (String(form.note ?? "").trim()) body.note = String(form.note).trim().slice(0, 200);
  return { body };
}

/** The figures of a ledger row without its label: "100 @ 80.00", "1 拆 2", "10,000.00". */
export function entryDetail(tx) {
  if (TRADE.has(tx.kind)) return `${formatShares(tx.quantity)} @ ${formatPrice(tx.price)}`;
  if (tx.kind === "split") return `1 拆 ${formatShares(tx.ratio)}`;
  return formatMoney(tx.amount, { signed: tx.kind === "cash_adjust" });
}

/** One ledger row as a line: "买入 100 @ 80.00 · 手续费 1.00". */
export function entryLine(tx) {
  const label = KIND_LABELS[tx.kind] ?? tx.kind;
  return `${label} ${entryDetail(tx)}${TRADE.has(tx.kind) && tx.fee ? ` · 手续费 ${formatMoney(tx.fee)}` : ""}`;
}

/** The plan form's fields as text, from a position's plan. */
export function planForm(plan) {
  const price = (v) => (v === null || v === undefined || v === "" ? "" : formatPrice(v).replace(/,/g, ""));
  return { plan_text: plan?.plan_text ?? "", add_price: price(plan?.add_price), stop_price: price(plan?.stop_price), target_price: price(plan?.target_price) };
}

/** PUT /plans/{symbol} replaces the plan: a blank price is sent as null (cleared). */
export function planBody(form) {
  const body = { plan_text: String(form?.plan_text ?? "").trim() };
  for (const key of ["add_price", "stop_price", "target_price"]) {
    const text = String(form?.[key] ?? "").trim();
    if (!text) { body[key] = null; continue; }
    const value = parseAmount(text);
    if (value === null) return { error: "价格要填不小于 0 的数字，不填表示不设。" };
    body[key] = value;
  }
  return { body };
}

export function planChanged(plan, form) {
  const now = planForm(plan);
  return ["plan_text", "add_price", "stop_price", "target_price"].some((key) => String(form?.[key] ?? "").trim() !== now[key]);
}

export const WARNING_LABELS = {
  available_funds_negative: "可用资金为负，请核对是否漏记了入金或可用资金。",
  price_missing: "有持仓没有取到最新价，总资产与仓位占比不完整。",
};
export const warningLabels = (codes) => (Array.isArray(codes) ? codes : []).map((code) => WARNING_LABELS[code]).filter(Boolean);
