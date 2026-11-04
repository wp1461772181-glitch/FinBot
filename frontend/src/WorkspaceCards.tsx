// The bot workspace's data cards (UX batch 2, P3).  Each card loads on its own, so one failing read never blanks
// the others.  Facts only: prices, dates, counts and titles; no buy/sell wording anywhere.
import { useEffect, useState } from "react";
import { getFilingInventory, getMaterialLibrary, getPortfolio, getResearchQueue, getV2Forecasts, getV2Prices, listAgentTasks, listInbox, listTaskProposals, type Bot } from "./api";
import { formatDate, getLocalePreference, useLocale } from "./i18n";
import { CARDS, forecastCardModel, priceSummary, type LayoutItem } from "./workspace-cards.mjs";
import { NOT_RECORDED } from "./forecast-model.mjs";
import { ProbabilityStrip, modelStatusText } from "./ForecastShared";
import type { V2ModelStatus } from "./types";
import { judgmentLink, waitingCount } from "./inbox-items.mjs";
import { formatMoney, formatPercent, pnlTone } from "./portfolio-items.mjs";
import { materialHref } from "./material-focus.mjs";

type Load<T> = { kind: "loading" } | { kind: "ready"; value: T } | { kind: "error" };
const cache = new Map<string, { at: number; value: unknown }>();
const CACHE_MS = 60_000;

function useLoad<T>(key: string, load: (signal: AbortSignal) => Promise<T>, cached = false): [Load<T>, () => void] {
  const [state, setState] = useState<Load<T>>({ kind: "loading" }), [tick, setTick] = useState(0);
  useEffect(() => {
    const hit = cached ? cache.get(key) : undefined;
    if (hit && Date.now() - hit.at < CACHE_MS && tick === 0) { setState({ kind: "ready", value: hit.value as T }); return; }
    const controller = new AbortController();
    setState({ kind: "loading" });
    load(controller.signal).then(value => { if (!controller.signal.aborted) { if (cached) cache.set(key, { at: Date.now(), value }); setState({ kind: "ready", value }); } })
      .catch(() => { if (!controller.signal.aborted) setState({ kind: "error" }); });
    return () => controller.abort();
  }, [key, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return [state, () => setTick(n => n + 1)];
}

const day = (value: string | null | undefined) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value.slice(0, 10) : formatDate(date, getLocalePreference(), "UTC");
};

function Body<T>({ state, empty, children }: { state: Load<T>; empty?: (value: T) => boolean; children: (value: T) => React.ReactNode }) {
  const { t } = useLocale();
  if (state.kind === "loading") return <p className="ws-muted" role="status">{t("正在读取…")}</p>;
  if (state.kind === "error") return <p className="ws-muted">{t("暂时读不到，稍后再试。")}</p>;
  if (empty?.(state.value)) return <p className="ws-muted">{t("暂无")}</p>;
  return <>{children(state.value)}</>;
}

function Sparkline({ closes, wide }: { closes: number[]; wide: boolean }) {
  if (closes.length < 2) return null;
  const w = wide ? 520 : 260, h = wide ? 120 : 48, min = Math.min(...closes), max = Math.max(...closes), span = max - min || 1;
  const points = closes.map((c, i) => `${(i / (closes.length - 1)) * w},${h - ((c - min) / span) * (h - 4) - 2}`).join(" ");
  return <svg className="ws-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="3M"><polyline points={points} fill="none" stroke="currentColor" strokeWidth={wide ? 1.6 : 1.3} vectorEffect="non-scaling-stroke" /></svg>;
}

function PriceCard({ symbol, wide }: { symbol: string; wide: boolean }) {
  const { t } = useLocale();
  const [state] = useLoad(`price:${symbol}`, signal => getV2Prices(symbol, signal), true);
  return <Body state={state} empty={v => !v.price_history.candles.length}>{v => {
    const candles = v.price_history.candles, s = priceSummary(candles);
    if (!s) return <p className="ws-muted">{t("暂无")}</p>;
    const dir = s.change === null || s.change === 0 ? "flat" : s.change > 0 ? "up" : "down";
    const sign = s.change && s.change > 0 ? "+" : "";
    return <>
      <p className="ws-price"><strong className="num">{s.close.toFixed(2)}</strong>
        {s.change !== null && <span className={`delta delta-${dir}`}>{dir === "up" ? "↑" : dir === "down" ? "↓" : "→"} {sign}{s.change.toFixed(2)} ({sign}{(s.pct ?? 0).toFixed(2)}%)</span>}</p>
      <Sparkline closes={candles.slice(-63).map(c => c.close)} wide={wide} />
      <small className="ws-muted">{t("收盘")} {s.date} · {t("近 3 个月")}</small>
    </>;
  }}</Body>;
}

// One list call for this card's stock (the workspace read has no deciding model, target date or rootId in the row
// shape the home page uses).  The card links to that forecast's own page, #forecast/<rootId>.
function ForecastCard({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  const [state] = useLoad(`forecast:${symbol}`, signal => getV2Forecasts({ symbols: [symbol], state: "all", limit: 20 }, signal)
    .then(list => forecastCardModel(list.forecasts, symbol)));
  return <>
    <Body state={state} empty={v => v === null}>{v => v && <>
      <p><strong>{t("决策模型")}</strong> {v.model ?? t(NOT_RECORDED)} · {t("目标日")} {v.targetDate ?? t(NOT_RECORDED)}</p>
      {v.probabilities ? <ProbabilityStrip probabilities={v.probabilities} label={t("三类概率")} compact /> : <p className="ws-muted">{modelStatusText(v.modelStatus as V2ModelStatus)}</p>}
      <small className="ws-muted">{t("最新版本")} v{v.versionNo} · {t("决策日")} {day(v.decisionAt)}</small>
      <a className="text-button" href={v.hash}>{t("打开这份预测")} →</a></>}</Body>
    <small className="ws-muted ws-fine">{t("模型意见，未经校准，仅供参考。")}</small>
  </>;
}

function MaterialsCard({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  const [state] = useLoad(`materials:${symbol}`, signal => getMaterialLibrary(symbol, { order: "recent", limit: 5, signal }));
  const fresh = (value: string | null) => Boolean(value && Date.now() - new Date(value).valueOf() < 24 * 3600 * 1000);
  return <>
    <Body state={state} empty={v => !v.items.length}>{v => <ul className="ws-list">{v.items.map(item =>
      <li key={`${item.source_type}:${item.source_id}`}><a href={materialHref(symbol, item)}>{item.title}</a>
        {fresh(item.observed_at) && <span className="ws-new">{t("新")}</span>}<small className="ws-muted"> {day(item.published_at)}</small></li>)}</ul>}</Body>
    <a className="text-button" href={`#materials?symbol=${encodeURIComponent(symbol)}`}>{t("打开资料库")} →</a>
  </>;
}

function FilingsCard({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  const [state] = useLoad(`filings:${symbol}`, signal => getFilingInventory(symbol, signal), true);
  return <>
    <Body state={state} empty={v => !v.filings.length}>{v => <ul className="ws-list">{[...v.filings].sort((a, b) => b.filed_at.localeCompare(a.filed_at)).slice(0, 5).map(f =>
      <li key={f.accession_number}><a href={f.source_url} target="_blank" rel="noreferrer">{f.form}</a><small className="ws-muted"> {day(f.filed_at)}</small></li>)}</ul>}</Body>
    <a className="text-button" href={`#materials?symbol=${encodeURIComponent(symbol)}`}>{t("去资料库扫描新申报")} →</a>
  </>;
}

// 例行任务 (it took in the 待你确认 card): this bot's routines, and how many of its cards wait for the owner —
// routine cards proposed in chat and writes its unattended runs suggested — with the way to the 例行任务 page.
function RoutinesCard({ bot }: { bot: Bot }) {
  const { t } = useLocale();
  const [state] = useLoad(`routines:${bot.id}`, signal => Promise.all([listAgentTasks(signal, bot.id), listTaskProposals(signal),
    listInbox("confirm", signal, bot.id)]).then(([tasks, proposals, confirms]) => ({ tasks,
      waiting: waitingCount(bot.id, proposals, confirms) })));
  return <>
    <Body state={state} empty={v => !v.tasks.length && !v.waiting}>{v => <>
      {v.waiting > 0 && <p><a href="#routines">{v.waiting} {t("项等你确认")} →</a></p>}
      <ul className="ws-list">{v.tasks.slice(0, 5).map(task =>
        <li key={task.id}><span>{task.name}{task.enabled ? "" : ` · ${t("已停用")}`}</span>
          <small className="ws-muted"> {t("下次")} {day(task.next_run_at)}{task.last_status_label ? ` · ${t("上次")} ${t(task.last_status_label)}` : ""}</small></li>)}</ul></>}</Body>
    <a className="text-button" href="#routines">{t("管理例行任务")} →</a>
  </>;
}

// 我的持仓: the owner's funds, total, P&L and the biggest positions; the full table is on the 持仓 page.  Owner only
// (a guest's read answers 403, which shows as the card's usual error line).
function PortfolioCard() {
  const { t } = useLocale();
  const [state] = useLoad("portfolio", signal => getPortfolio(signal));
  return <>
    <Body state={state} empty={v => !v.positions.length && Number(v.available_funds) === 0 && !v.transactions.length}>{v => <>
      <ul className="ws-list">
        <li><span>{t("可用资金")}</span> <strong>{formatMoney(v.available_funds)}</strong></li>
        <li><span>{t("总资产")}</span> <strong>{v.total_assets === null ? "—" : formatMoney(v.total_assets)}</strong></li>
        <li><span>{t("浮动盈亏")}</span> <strong className={`pf-${pnlTone(v.floating_pnl)}`}>{formatMoney(v.floating_pnl, { signed: true })}</strong></li>
        <li><span>{t("今日盈亏")}{v.today_pnl_reference_only ? ` · ${t("仅供参考")}` : ""}</span> <strong className={`pf-${pnlTone(v.today_pnl)}`}>{formatMoney(v.today_pnl, { signed: true })}</strong></li>
      </ul>
      <ul className="ws-list">{[...v.positions].sort((a, b) => Number(b.weight_pct ?? 0) - Number(a.weight_pct ?? 0)).slice(0, 5).map(p =>
        <li key={p.symbol}><span>{p.symbol}</span><small className="ws-muted"> {t("仓位占比")} {formatPercent(p.weight_pct)} · <span className={`pf-${pnlTone(p.floating_pnl)}`}>{formatMoney(p.floating_pnl, { signed: true })}</span></small></li>)}</ul>
      {v.price_date && <small className="ws-muted">{t("行情数据日期")} {v.price_date}</small>}</>}</Body>
    <a className="text-button" href="#portfolio">{t("管理持仓")} →</a>
  </>;
}

function BriefCard({ bot }: { bot: Bot }) {
  const [state] = useLoad(`brief:${bot.id}`, signal => listInbox("brief", signal, bot.id));
  return <Body state={state} empty={v => !v.length}>{v => <ul className="ws-list">{v.slice(0, 3).map(item =>
    <li key={item.id}>{judgmentLink(item) ? <a href={judgmentLink(item)!}>{item.title}</a> : <span>{item.title}</span>}<small className="ws-muted"> {day(item.created_at)}</small></li>)}</ul>}</Body>;
}

function WatchlistCard({ onPick }: { onPick: (symbol: string) => void }) {
  const [state] = useLoad("watchlist", signal => getResearchQueue(signal).then(v => v ?? []));
  return <Body state={state} empty={v => !v.length}>{v => <div className="ws-chips">{v.map(s => <button key={s} type="button" className="bot-chip" onClick={() => onPick(s)}>{s}</button>)}</div>}</Body>;
}

export function WorkspaceCard({ item, bot, symbol, wide, onOpenCompany, onPickSymbol, editing, controls }: {
  item: LayoutItem; bot: Bot; symbol: string; wide: boolean; editing: boolean; controls?: React.ReactNode;
  onOpenCompany: (ticker: string, section?: "overview" | "forecast") => void; onPickSymbol: (symbol: string) => void }) {
  const { t } = useLocale();
  const card = CARDS.find(c => c.id === item.card)!;
  const sym = item.symbol || symbol;
  const body = item.card === "price" ? <PriceCard symbol={sym} wide={wide || item.size === "l"} />
    : item.card === "forecast" ? <ForecastCard symbol={sym} />
    : item.card === "materials" ? <MaterialsCard symbol={sym} />
    : item.card === "filings" ? <FilingsCard symbol={sym} />
    : item.card === "routines" ? <RoutinesCard bot={bot} />
    : item.card === "brief" ? <BriefCard bot={bot} />
    : item.card === "portfolio" ? <PortfolioCard />
    : <WatchlistCard onPick={onPickSymbol} />;
  const perStock = ["price", "forecast", "materials", "filings"].includes(item.card);
  return <section className={`ws-card size-${item.size ?? card.size}`} aria-label={t(card.title)}>
    <header><h4>{t(card.title)}{perStock ? <small className="ws-muted"> · {sym}</small> : null}</h4>{controls}</header>
    {editing ? null : body}
  </section>;
}
