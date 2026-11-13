// 持仓: a small manual ledger (money as decimal strings).
import { candles, lastClose, daysAgo, dayOnly } from "./common.mjs";

const HOLDINGS = [["AAPL", 150, 188.4], ["NVDA", 300, 104.2], ["TSLA", 40, 255.0], ["MSFT", 25, 396.5]];
const fix = (n) => (Math.round(n * 100) / 100).toFixed(2);

export function portfolioSummary(state) {
  const positions = HOLDINGS.map(([symbol, shares, avg]) => {
    const rows = candles(symbol); const price = rows.at(-1).close; const prev = rows.at(-2).close;
    const cost = shares * avg; const value = shares * price;
    return { symbol, shares: String(shares), cost: fix(cost), avg_cost: fix(avg), diluted_cost: fix(avg), realized_pnl: symbol === "TSLA" ? "412.50" : "0.00", price: fix(price), price_date: rows.at(-1).trading_date,
      market_value: fix(value), floating_pnl: fix(value - cost), floating_pnl_pct: fix(((value - cost) / cost) * 100), today_pnl: fix(shares * (price - prev)), today_pnl_reference_only: false, weight_pct: null,
      plan: state.portfolio.plans[symbol] ?? { plan_text: "", add_price: null, stop_price: null, target_price: null } };
  });
  const total = positions.reduce((s, p) => s + Number(p.market_value), 0);
  positions.forEach((p) => { p.weight_pct = fix((Number(p.market_value) / total) * 100); });
  const funds = Number(state.portfolio.cash);
  return { available_funds: state.portfolio.cash, positions_value: fix(total), total_assets: fix(total + funds), total_assets_complete: true,
    floating_pnl: fix(positions.reduce((s, p) => s + Number(p.floating_pnl), 0)), today_pnl: fix(positions.reduce((s, p) => s + Number(p.today_pnl), 0)), today_pnl_reference_only: false,
    realized_pnl: "412.50", price_date: candles("AAPL").at(-1).trading_date, unpriced: [], warnings: [], positions, plans_without_position: Object.keys(state.portfolio.plans).filter((s) => !HOLDINGS.some(([h]) => h === s)), transactions: state.portfolio.transactions };
}

export function buildPortfolio() {
  const tx = (n, symbol, kind, quantity, price, ago, note = "") => ({ id: `p0000000-0000-4000-8000-${String(n).padStart(12, "0")}`, symbol, kind, quantity: quantity == null ? null : String(quantity), price: price == null ? null : fix(price), fee: kind === "buy" || kind === "sell" ? "1.00" : null,
    amount: kind === "dividend" ? "36.00" : null, ratio: null, occurred_on: dayOnly(ago), note, created_at: daysAgo(ago) });
  return { cash: "25800.00", plans: {
    AAPL: { plan_text: "回调到 200 附近分批加仓；跌破 185 止损。", add_price: "200.00", stop_price: "185.00", target_price: "235.00", updated_at: daysAgo(6) },
    NVDA: { plan_text: "财报后观察，目标位 140。", add_price: null, stop_price: "105.00", target_price: "140.00", updated_at: daysAgo(9) },
    AMD: { plan_text: "等待回踩再考虑建仓。", add_price: "135.00", stop_price: null, target_price: null, updated_at: daysAgo(12) } },
    transactions: [tx(1, "AAPL", "buy", 100, 182.0, 160), tx(2, "AAPL", "buy", 50, 201.2, 75), tx(3, "NVDA", "buy", 300, 104.2, 120, "财报前建仓"), tx(4, "TSLA", "buy", 60, 250.0, 95), tx(5, "TSLA", "sell", 20, 270.6, 41, "部分止盈"),
      tx(6, "MSFT", "buy", 25, 396.5, 58), tx(7, "AAPL", "dividend", null, null, 30), tx(8, "MSFT", "dividend", null, null, 12)].sort((a, b) => b.occurred_on.localeCompare(a.occurred_on)) };
}
export { lastClose };
