import { useCallback, useEffect, useState } from "react";
import { addPortfolioTransaction, deletePortfolioTransaction, getPortfolio, putPortfolioCash, putPortfolioPlan, type PortfolioPosition, type PortfolioSummary } from "./api";
import { translatePhrase, useLocale } from "./i18n";
import { ENTRY_KINDS, KIND_LABELS, blankEntry, entryBody, entryDetail, formatMoney, formatPercent, formatPrice, formatShares, parseAmount, planBody, planChanged, planForm, pnlTone, warningLabels, type PortfolioEntryForm, type PortfolioPlanForm } from "./portfolio-items.mjs";

// The 持仓 page (personal finance assistant, Task 6): positions with average cost (primary) and diluted cost, floating and
// today's P&L, weight, 可用资金 (the owner's money for adding positions, not a company's free cash flow), the owner's own
// plan per position, and the ledger.  Manual entry here or by telling the assistant; no broker statement import in v1.
// Facts and the owner's own plan prices only: nothing here recommends a trade.

const message = (error: unknown, fallback: string) => translatePhrase(error instanceof Error ? error.message : fallback);
const TRADE_KINDS = new Set(["opening", "buy", "sell"]);
const CASH_KINDS = new Set(["deposit", "withdraw"]);

function Money({ value, signed = false, tone = false }: { value: string | null | undefined; signed?: boolean; tone?: boolean }) {
  return <span className={tone ? `pf-${pnlTone(value)}` : undefined}>{formatMoney(value, { signed })}</span>;
}

export function PortfolioPage() {
  const { t } = useLocale();
  const [data, setData] = useState<PortfolioSummary | null>(null), [error, setError] = useState(""), [status, setStatus] = useState(""), [busy, setBusy] = useState(false);
  const [entryOpen, setEntryOpen] = useState(false), [entry, setEntry] = useState<PortfolioEntryForm>(blankEntry()), [entryError, setEntryError] = useState("");
  const [fundsEdit, setFundsEdit] = useState<string | null>(null);
  const [plans, setPlans] = useState<Record<string, PortfolioPlanForm>>({});

  const load = useCallback((signal?: AbortSignal) => getPortfolio(signal).then(next => { setData(next); setError(""); })
    .catch(e => { if (!signal?.aborted) setError(message(e, "持仓暂时无法读取。")); }), []);
  useEffect(() => { const ctrl = new AbortController(); void load(ctrl.signal); return () => ctrl.abort(); }, [load]);

  async function act(work: () => Promise<{ warnings?: string[] } | unknown>, done: string) {
    setBusy(true); setStatus(""); setError("");
    try {
      const result = await work() as { warnings?: string[] };
      await load();
      const warned = warningLabels(result?.warnings).map(w => t(w)).join(" ");
      setStatus(`${t(done)}${warned ? " " + warned : ""}`);
      return true;
    } catch (e) { setError(message(e, "操作失败，请重试。")); return false; } finally { setBusy(false); }
  }
  async function submitEntry() {
    const built = entryBody(entry);
    if ("error" in built) { setEntryError(t(built.error)); return; }
    setEntryError("");
    if (await act(() => addPortfolioTransaction(built.body), "已记录。")) { setEntry(blankEntry(entry.kind)); }
  }
  async function saveFunds() {
    if (fundsEdit === null) return;
    const value = parseAmount(fundsEdit, { allowNegative: true });
    if (value === null) { setError(t("金额要填数字。")); return; }
    if (await act(() => putPortfolioCash(value), "可用资金已更新。")) setFundsEdit(null);
  }
  async function savePlan(position: PortfolioPosition) {
    const form = plans[position.symbol] ?? planForm(position.plan);
    const built = planBody(form);
    if ("error" in built) { setError(t(built.error)); return; }
    await act(() => putPortfolioPlan(position.symbol, built.body), "计划已保存。");
  }
  async function remove(id: string) {
    if (!window.confirm(t("删除这一笔记录？持仓和可用资金会按剩下的记录重新计算。"))) return;
    await act(() => deletePortfolioTransaction(id), "已删除。");
  }

  const setField = (key: keyof PortfolioEntryForm, value: string) => setEntry(current => ({ ...current, [key]: value }));
  const kind = entry.kind;
  const field = (key: keyof PortfolioEntryForm, label: string, extra: { inputMode?: "decimal" | "text"; placeholder?: string; maxLength?: number } = {}) =>
    <label>{t(label)}<input type="text" value={entry[key]} inputMode={extra.inputMode} placeholder={extra.placeholder ? t(extra.placeholder) : undefined} maxLength={extra.maxLength} onChange={e => setField(key, e.target.value)} /></label>;

  const warnings = warningLabels(data?.warnings);
  return <main className="personal-page portfolio-page" aria-labelledby="portfolio-title">
    <h1 id="portfolio-title">{t("持仓")}</h1>
    <p className="fine-print">{t("手填或在对话里告诉助理（会先出确认卡）。这里只记录你自己的持仓和计划，不是买卖建议；第一版不支持导入券商对账单。")}</p>
    {error && <p role="alert">{error}</p>}
    {status && <p role="status">{status}</p>}
    {!data && !error && <p role="status">{t("正在读取…")}</p>}

    {data && <>
      <section className="pf-summary" aria-label={t("账户汇总")}>
        <div className="personal-card pf-stat">
          <small>{t("可用资金")}</small>
          {fundsEdit === null
            ? <><strong><Money value={data.available_funds} /></strong>
                <button type="button" className="text-button" onClick={() => setFundsEdit(formatMoney(data.available_funds).replace(/,/g, ""))}>{t("修改")}</button></>
            : <form className="pf-inline" onSubmit={e => { e.preventDefault(); void saveFunds(); }}>
                <input type="text" inputMode="decimal" aria-label={t("可用资金")} value={fundsEdit} onChange={e => setFundsEdit(e.target.value)} />
                <button type="submit" className="primary-action" disabled={busy}>{t("保存")}</button>
                <button type="button" className="secondary-action" onClick={() => setFundsEdit(null)}>{t("取消")}</button></form>}
          <small className="ws-muted">{t("你自己可用于加仓、补仓的钱")}</small>
        </div>
        <div className="personal-card pf-stat"><small>{t("总资产")}</small><strong>{data.total_assets === null ? "—" : <Money value={data.total_assets} />}</strong>
          <small className="ws-muted">{t("持仓市值")} <Money value={data.positions_value} /></small></div>
        <div className="personal-card pf-stat"><small>{t("浮动盈亏")}</small><strong><Money value={data.floating_pnl} signed tone /></strong></div>
        <div className="personal-card pf-stat"><small>{t("今日盈亏")}{data.today_pnl_reference_only ? ` · ${t("仅供参考")}` : ""}</small>
          <strong><Money value={data.today_pnl} signed tone /></strong></div>
        <div className="personal-card pf-stat"><small>{t("已实现盈亏")}</small><strong><Money value={data.realized_pnl} signed tone /></strong></div>
      </section>
      <p className="fine-print">{data.price_date ? `${t("行情数据日期")} ${data.price_date}` : t("还没有可用的行情数据。")}</p>
      {warnings.map(w => <p key={w} role="status">{t(w)}</p>)}

      <section className="pf-positions" aria-label={t("持仓列表")}>
        {data.positions.length === 0 && <p className="fine-print">{t("还没有持仓。点「记一笔」添加，或对助理说「我买了 100 股 INTC，成本 80」。")}</p>}
        {data.positions.map(position => {
          const form = plans[position.symbol] ?? planForm(position.plan);
          const setPlan = (key: keyof PortfolioPlanForm, value: string) => setPlans(current => ({ ...current, [position.symbol]: { ...form, [key]: value } }));
          return <article className="personal-card pf-position" key={position.symbol}>
            <div className="memory-line"><h2>{position.symbol}</h2><span className="fine-print">{formatShares(position.shares)} {t("股")}</span>
              {position.weight_pct !== null && <span className="personal-badge">{t("仓位占比")} {formatPercent(position.weight_pct)}</span>}</div>
            <dl className="pf-grid">
              <div><dt>{t("平均成本")}</dt><dd><strong>{formatPrice(position.avg_cost)}</strong></dd></div>
              <div><dt>{t("摊薄成本")}</dt><dd>{formatPrice(position.diluted_cost)}</dd></div>
              <div><dt>{t("最新价")}</dt><dd>{position.price === null ? t("暂无") : formatPrice(position.price)}{position.price_date && <small className="ws-muted"> {position.price_date}</small>}</dd></div>
              <div><dt>{t("市值")}</dt><dd><Money value={position.market_value} /></dd></div>
              <div><dt>{t("浮动盈亏")}</dt><dd><Money value={position.floating_pnl} signed tone />{position.floating_pnl_pct !== null && <small className="ws-muted"> {formatPercent(position.floating_pnl_pct, { signed: true })}</small>}</dd></div>
              <div><dt>{t("今日盈亏")}</dt><dd><Money value={position.today_pnl} signed tone />{position.today_pnl_reference_only && <small className="ws-muted"> {t("仅供参考")}</small>}</dd></div>
            </dl>
            <form className="task-form pf-plan" aria-label={`${position.symbol} ${t("计划")}`} onSubmit={e => { e.preventDefault(); void savePlan(position); }}>
              <label>{t("我的计划")}<textarea rows={2} maxLength={2000} value={form.plan_text} placeholder={t("例如：跌到补仓价分两次补，破止损价就走")} onChange={e => setPlan("plan_text", e.target.value)} /></label>
              <div className="pf-prices">
                <label>{t("补仓价")}<input type="text" inputMode="decimal" value={form.add_price} onChange={e => setPlan("add_price", e.target.value)} /></label>
                <label>{t("止损价")}<input type="text" inputMode="decimal" value={form.stop_price} onChange={e => setPlan("stop_price", e.target.value)} /></label>
                <label>{t("目标价")}<input type="text" inputMode="decimal" value={form.target_price} onChange={e => setPlan("target_price", e.target.value)} /></label>
              </div>
              <div className="memory-actions"><button type="submit" className="secondary-action" disabled={busy || !planChanged(position.plan, form)}>{t("保存计划")}</button></div>
            </form>
          </article>;
        })}
      </section>

      <div className="memory-actions">
        <button type="button" className="primary-action" onClick={() => { setEntryOpen(open => !open); setEntryError(""); }}>{t("记一笔")}</button>
      </div>
      {entryOpen && <form className="task-form pf-entry" aria-label={t("记一笔")} onSubmit={e => { e.preventDefault(); void submitEntry(); }}>
        <label>{t("类型")}<select value={kind} onChange={e => setEntry(blankEntry(e.target.value))}>
          {ENTRY_KINDS.map(k => <option key={k} value={k}>{t(KIND_LABELS[k])}</option>)}</select></label>
        {!CASH_KINDS.has(kind) && field("symbol", "股票代码", { placeholder: "例如 INTC", maxLength: 12 })}
        {TRADE_KINDS.has(kind) && <>{field("quantity", "股数", { inputMode: "decimal" })}{field("price", kind === "opening" ? "平均成本（每股）" : "成交价", { inputMode: "decimal" })}</>}
        {TRADE_KINDS.has(kind) && kind !== "opening" && field("fee", "手续费（可不填）", { inputMode: "decimal" })}
        {kind === "split" && field("ratio", "拆股比例（1 拆 2 填 2）", { inputMode: "decimal" })}
        {(kind === "dividend" || CASH_KINDS.has(kind)) && field("amount", "金额", { inputMode: "decimal" })}
        <label>{t("日期（可不填，默认今天）")}<input type="date" value={entry.occurred_on} onChange={e => setField("occurred_on", e.target.value)} /></label>
        {field("note", "备注（可不填）", { maxLength: 200 })}
        {kind === "opening" && <p className="fine-print">{t("期初持仓是你已经持有的仓位，不会改变可用资金。")}</p>}
        {entryError && <p role="alert">{entryError}</p>}
        <div className="memory-actions"><button type="submit" className="primary-action" disabled={busy}>{t("记录")}</button></div>
      </form>}

      {data.transactions.length > 0 && <section aria-label={t("记录")}>
        <h2>{t("记录")}</h2>
        <ul className="ws-list pf-ledger">{data.transactions.map(tx => <li key={tx.id}>
          <span className="ws-muted">{tx.occurred_on}</span> <strong>{tx.symbol || ""}</strong> <span>{t(KIND_LABELS[tx.kind] ?? tx.kind)} {entryDetail(tx)}{tx.kind in { opening: 1, buy: 1, sell: 1 } && tx.fee ? ` · ${t("手续费")} ${formatMoney(tx.fee)}` : ""}</span>
          {tx.note && <small className="ws-muted"> · {tx.note}</small>}
          <button type="button" className="text-button" disabled={busy} onClick={() => void remove(tx.id)}>{t("删除")}</button></li>)}</ul>
      </section>}
    </>}
  </main>;
}

export function PortfolioIcon() {
  return <svg className="portfolio-icon" viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path d="M4 20V10M10 20V5M16 20v-7M22 20H2" />
  </svg>;
}
