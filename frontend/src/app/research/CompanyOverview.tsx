import { useMemo, useState } from "react";
import { Link } from "react-router";
import { ArrowRight, ExternalLink } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { CandlestickChart } from "../../CandlestickChart";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { SkeletonCard } from "@/components/state/Skeleton";
import { StatefulButton } from "@/components/state/StatefulButton";
import { notify } from "@/components/state/notify";
import { OpinionCard } from "@/components/OpinionCard";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { StatTile, Change } from "@/components/StatTile";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import { getEarningsJudgments, getV2Forecasts, getV2MonitorStatus } from "../../api/forecast-v2";
import { getMaterialLibrary } from "../../api/material-library";
import { getFilingInventory, initializeMarketData } from "../../api/market-data";
import type { PriceHistory } from "../../types";
import { companyIsEmpty } from "../../company-page.mjs";
import { monitorChip, signedChange, usableCandles } from "../../data-display.mjs";
import { forecastBySymbol, judgmentLane } from "../../forecast-home.mjs";
import { formatDate, getLocalePreference, useLocale } from "../../i18n";
import { researchRecord } from "../../portfolio-items.mjs";
import { appHref } from "../../legacy-routes.mjs";
import { paths } from "../../routes.mjs";
import { useWorkspace } from "../workspace";
import { actionMessage } from "./support";
import { useRead, type Read } from "./use-read";

const day = (value: string | null | undefined) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value.slice(0, 10) : formatDate(date, getLocalePreference(), "UTC");
};

/** The empty market card: no candles saved.  The way to get them (一年行情 from the data supplier) is here, not at the foot of the page. */
function InitPrices({ symbol, onDone, compact = false }: { symbol: string; onDone: () => void; compact?: boolean }) {
  const { t } = useLocale();
  const run = async () => {
    const result = await initializeMarketData(symbol);
    if (!result.inserted_count) notify.info(t("初始化完成，但供应商没有返回可保存的行情。"));
    onDone();
  };
  return <StatefulButton type="button" variant={compact ? "outline" : "default"} data-testid="init-prices" onClick={run}
    onError={error => notify.error(actionMessage(error, "行情初始化失败，请登录个人账户后重试。"))}>{t("初始化一年行情")}</StatefulButton>;
}

/** The market card (fact material): the saved candles with the forecast's time marks on them, and the readout of the candle the pointer or focus is on. */
function MarketCard({ symbol, prices, reloadPrices, forecast }: { symbol: string; prices: Read<{ price_history: PriceHistory }>; reloadPrices: () => void; forecast: { decision_at: string; target_end_date: string | null } | null }) {
  const { t } = useLocale();
  const history = prices.kind === "ready" ? prices.value.price_history : null;
  const candles = useMemo(() => usableCandles(history?.candles), [history]);
  const [active, setActive] = useState<string | null>(null);
  const shown = candles.find(candle => candle.trading_date === active) ?? candles.at(-1) ?? null;
  const shownChange = shown ? signedChange(shown.close - shown.open, { digits: 2 }) : null;
  return <section data-testid="company-market" aria-label={t("行情")} className="material-fact flex min-w-0 flex-col gap-2 p-4">
    <div className="flex flex-wrap items-baseline gap-x-3">
      <h2 className="text-title-s text-ink">{t("行情")}</h2>
      {history?.latest_trading_date && <p className="font-mono text-caption text-muted-foreground">{t("行情截至")} {history.latest_trading_date}</p>}
    </div>
    {prices.kind === "loading" && <SkeletonCard className="border-0 bg-transparent p-0" />}
    {prices.kind === "error" && <ErrorBar message={actionMessage(prices.error, "行情暂不可用。")} onRetry={reloadPrices} />}
    {prices.kind === "ready" && (candles.length === 0
      ? <EmptyState title={t("本地没有可展示的行情")} description={t("初始化会从数据供应商取回约一年的日线并保存到本地。")} className="py-6"><InitPrices symbol={symbol} onDone={reloadPrices} /></EmptyState>
      : <>
        <CandlestickChart candles={candles} symbol={symbol} activeDate={shown!.trading_date} onInspect={setActive}
          cutoffDate={forecast?.decision_at.slice(0, 10)} targetEndDate={forecast?.target_end_date ?? undefined} />
        <p data-testid="candle-readout" aria-live="polite" className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-caption tabular-nums text-muted-foreground">
          <span className="text-ink">{shown!.trading_date}</span>
          <span>{t("开盘")} {shown!.open.toFixed(2)}</span><span>{t("最高")} {shown!.high.toFixed(2)}</span><span>{t("最低")} {shown!.low.toFixed(2)}</span><span>{t("收盘")} {shown!.close.toFixed(2)}</span>
          {shownChange && <Change direction={shownChange.direction} text={shownChange.text} />}
        </p>
      </>)}
  </section>;
}

/** A list in the fact material: a title, its rows, and a way on. */
function FactList({ title, label, children, more }: { title: string; label: string; children: React.ReactNode; more?: React.ReactNode }) {
  return <section aria-label={label} className="material-fact flex min-w-0 flex-col gap-2 p-4">
    <h2 className="text-title-s text-ink">{title}</h2>
    {children}
    {more && <div className="mt-auto pt-1 text-small">{more}</div>}
  </section>;
}
const rowLink = "inline-flex items-center gap-1 rounded-sm text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring";

/**
 * The overview tab (design 4.5): four key numbers, the market card, the latest judgment (the opinion material), the latest materials and the official filings
 * (fact material).  Each block reads and fails on its own; a company with nothing at all gets one empty state with the way to start (the prices).
 */
export function CompanyOverview({ symbol, prices, reloadPrices }: { symbol: string; prices: Read<{ price_history: PriceHistory }>; reloadPrices: () => void }) {
  const { t, locale } = useLocale();
  const ws = useWorkspace();
  const [forecasts, retryForecasts] = useRead(`forecasts:${symbol}`, signal => getV2Forecasts({ symbols: [symbol], state: "all", limit: 20 }, signal));
  const [materials, retryMaterials] = useRead(`materials:${symbol}`, signal => getMaterialLibrary(symbol, { order: "recent", limit: 5, signal }));
  const [filings, retryFilings] = useRead(`filings:${symbol}`, signal => getFilingInventory(symbol, signal));
  const [monitor] = useRead("monitor", signal => getV2MonitorStatus(signal));
  const [judgments] = useRead(`judgments:${symbol}`, signal => getEarningsJudgments({ limit: 100 }, signal).then(value => ({ lane: judgmentLane({ status: "fulfilled", value }) })).catch(reason => ({ lane: judgmentLane({ status: "rejected", reason }) })), ws.personal);

  const rows = forecasts.kind === "ready" ? forecasts.value.forecasts : [];
  const own = forecastBySymbol(rows).get(symbol.toUpperCase()) ?? [];
  const latest = own.find(row => !row.expired) ?? own[0] ?? null;
  const jobs = forecasts.kind === "ready" ? forecasts.value.job_alerts.filter(alert => alert.symbol === symbol && (alert.status === "queued" || alert.status === "running")).length : 0;
  const lane = judgments.kind === "ready" ? judgments.value.lane : null;
  const judgment = researchRecord(symbol, rows, (lane?.lane === "ready" ? lane.judgments : []) as Parameters<typeof researchRecord>[2]).judgment;
  const chip = monitor.kind === "ready" ? monitorChip(monitor.value.health) : null;

  const empty = companyIsEmpty({
    prices: prices.kind === "ready" ? usableCandles(prices.value.price_history.candles).length : null,
    forecasts: forecasts.kind === "ready" ? own.length : null,
    materials: materials.kind === "ready" ? materials.value.total : null,
    filings: filings.kind === "ready" ? filings.value.filings.length : null,
  });
  if (empty) {
    return <div data-testid="company-empty"><EmptyState title={locale === "en-US" ? `No data for ${symbol} yet` : `还没有 ${symbol} 的任何数据`} description={t("没有行情、预测、材料和官方申报。可以先初始化一年行情，再去材料库扫描 SEC 或创建预测。")} className="rounded-md border border-line bg-surface">
      <InitPrices symbol={symbol} onDone={reloadPrices} />
    </EmptyState></div>;
  }
  const dash = (value: number | null | undefined) => value ?? "—";
  const latestFilings = filings.kind === "ready" ? [...filings.value.filings].sort((a, b) => b.filed_at.localeCompare(a.filed_at)).slice(0, 5) : [];
  const lastSuccess = monitor.kind === "ready" ? monitor.value.last_success?.completed_at : null;
  return <div data-testid="company-overview" className="flex flex-col gap-4">
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label={t("当前研究状态")}>
      <StatTile label={t("独立预测数")} value={forecasts.kind === "ready" ? own.length : "—"} footnote={jobs ? `${jobs} ${t("项任务处理中")}` : t("按当前预测记录统计")} />
      <StatTile label={t("材料总数")} value={dash(materials.kind === "ready" ? materials.value.total : null)} footnote={t("已保存官方和上传材料")} />
      <StatTile label={t("SEC 官方材料")} value={dash(filings.kind === "ready" ? filings.value.filings.length : null)} footnote={filings.kind === "error" ? t("官方资料目录暂不可用") : t("当前股票已保存的官方文件")} />
      <StatTile label={t("监控状态")} value={monitor.kind === "loading" ? t("正在读取") : chip ? t(chip.phrase) : t("暂不可用")}
        footnote={monitor.kind === "error" ? t("无法读取监控状态") : lastSuccess ? `${t("最近成功")} ${day(lastSuccess)}` : monitor.kind === "ready" ? t("尚无成功运行记录") : t("正在读取监控记录")} />
    </div>
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)] lg:grid-rows-[auto_1fr]">
      <div className="lg:col-start-1 lg:row-start-1"><MarketCard symbol={symbol} prices={prices} reloadPrices={reloadPrices} forecast={latest} /></div>
      <div className="lg:col-start-2 lg:row-span-2 lg:row-start-1" data-testid="company-judgment">
        {forecasts.kind === "loading" && <SkeletonCard />}
        {forecasts.kind === "error" && <ErrorBar message={t("暂时无法读取预测。")} onRetry={retryForecasts} />}
        {forecasts.kind === "ready" && (latest
          ? <OpinionCard model={latest.decider.actual_model ?? t("未记录")} version={`v${latest.latest_version_no}`} time={day(latest.decision_at)} disclaimer>
            <h2 className="sr-only">{t("最新判断")}</h2>
            <ProbabilityBar probabilities={latest.probabilities} status={latest.model_status} />
            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-small">
              <dt className="text-muted-foreground">{t("目标日")}</dt><dd data-testid="judgment-target" className="m-0 font-mono tabular-nums text-ink">{latest.target_end_date ?? "—"}{latest.expired && <> <StatusBadge kind="neutral" className="ml-1 h-5">{t("已到期")}</StatusBadge></>}</dd>
              <dt className="text-muted-foreground">{t("决策日")}</dt><dd className="m-0 font-mono tabular-nums text-ink">{day(latest.decision_at)}</dd>
            </dl>
            {judgment && <p className="m-0 text-small text-ink-2"><a className={rowLink} href={appHref(judgment.hash)}>{t(judgment.typeLabel)}</a> · {t(judgment.direction)} · {t(judgment.result)}</p>}
            <Link to={paths.forecast(latest.id)} data-testid="open-forecast" className={cn(buttonVariants({ variant: "outline" }), "w-fit")}>{t("打开这项预测")}<ArrowRight aria-hidden="true" /></Link>
          </OpinionCard>
          : <section className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4" data-testid="judgment-none">
            <h2 className="text-title-s text-ink">{t("最新判断")}</h2>
            <p className="m-0 text-small text-muted-foreground">{t("这家公司还没有正式预测。历史行情与材料仍可查看，也可以直接创建预测。")}</p>
            <Link to={paths.forecasts({ symbol })} data-testid="create-forecast" className={cn(buttonVariants({ variant: "outline" }), "w-fit")}>{t("创建预测")}<ArrowRight aria-hidden="true" /></Link>
          </section>)}
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:col-start-1 lg:row-start-2">
        <FactList title={t("最近材料")} label={t("最近材料")} more={<Link className={rowLink} to={paths.company(symbol, "materials")}>{t("全部材料")}<ArrowRight aria-hidden="true" className="size-3.5" /></Link>}>
          {materials.kind === "loading" && <SkeletonCard className="border-0 bg-transparent p-0" />}
          {materials.kind === "error" && <ErrorBar message={t("暂时读不到，稍后再试。")} onRetry={retryMaterials} />}
          {materials.kind === "ready" && (materials.value.items.length
            ? <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-small">{materials.value.items.map(item => <li key={`${item.source_type}:${item.source_id}`} className="flex items-baseline justify-between gap-3">
              <Link className={cn(rowLink, "min-w-0 [overflow-wrap:anywhere]")} to={paths.materials({ symbol, focus: item.source_id, type: item.source_type })}>{item.title}</Link>
              <span className="shrink-0 font-mono text-caption text-muted-foreground">{day(item.published_at)}</span></li>)}</ul>
            : <p className="m-0 text-small text-muted-foreground">{t("暂无")}</p>)}
        </FactList>
        <FactList title={t("官方申报")} label={t("官方申报")} more={<Link className={rowLink} to={paths.company(symbol, "materials")}>{t("去材料库扫描新申报")}<ArrowRight aria-hidden="true" className="size-3.5" /></Link>}>
          {filings.kind === "loading" && <SkeletonCard className="border-0 bg-transparent p-0" />}
          {filings.kind === "error" && <ErrorBar message={actionMessage(filings.error, "暂时无法读取官方申报清单。")} onRetry={retryFilings} />}
          {filings.kind === "ready" && (latestFilings.length
            ? <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-small">{latestFilings.map(filing => <li key={filing.accession_number} className="flex items-baseline justify-between gap-3">
              <a className={rowLink} href={filing.source_url} target="_blank" rel="noopener noreferrer">{filing.form}<ExternalLink aria-hidden="true" className="size-3.5" /></a>
              <span className="shrink-0 font-mono text-caption text-muted-foreground">{day(filing.filed_at)}</span></li>)}</ul>
            : <p className="m-0 text-small text-muted-foreground">{t("暂无")}</p>)}
        </FactList>
      </div>
    </div>
  </div>;
}
