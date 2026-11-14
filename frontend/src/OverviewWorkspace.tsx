import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { Tx, formatDateTime as formatLocalizedDateTime, getLocalePreference, translatePhrase, useLocale } from "./i18n";
import { ApiError, type EarningsJudgment, type V2ForecastList, getEarningsJudgments, getMaterialLibrary, getV2Forecasts, getV2MonitorStatus, initializeMarketData } from "./api";
import { forecastBySymbol, judgmentLane, type JudgmentLane } from "./forecast-home.mjs";
import { researchRecord } from "./portfolio-items.mjs";
import type { FilingInventory, PriceHistory } from "./types";
import { modelStatusLabel } from "./ModelScoresPage";
import { MAX_WATCHLIST } from "./watchlist.mjs";
import { appHref } from "./legacy-routes.mjs";
import { hashHref, paths } from "./routes.mjs";
import { WORKSPACE_SECTION_TITLE, type ResearchSection, type SupportedSymbol, type WorkspaceSection } from "./workspace-sections.mjs";

// The research overview (moved out of App.tsx; P6.1 splits it into the watchlist page and the company page): the
// current stock's state, four counters and the watchlist grid, plus the page header and the intro the other
// research pages share.
export type FilingState = { kind: "idle" } | { kind: "loading" } | { kind: "ready"; data: FilingInventory } | { kind: "error"; message: string };

export function CurrentOverviewWorkspace({ symbols, personal, onRemove, symbol, currentFilings, priceHistory, priceError, onNavigate, onOpenStock, onPricesInitialized }: { symbols: string[]; personal: boolean; onRemove: (ticker: string) => void; symbol: string; currentFilings: FilingState; priceHistory: PriceHistory | null; priceError: string | null; onNavigate: (section: WorkspaceSection) => void; onOpenStock: (ticker: SupportedSymbol) => void; onPricesInitialized: () => void }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  // One forecast list feeds every queue card (no per-stock fan-out); materials and SEC counts belong to the current stock only.
  const [list, setList] = useState<{ kind: "loading" } | { kind: "ready"; data: V2ForecastList } | { kind: "error" }>({ kind: "loading" });
  const [lane, setLane] = useState<JudgmentLane<EarningsJudgment> | null>(null);
  const [materialCount, setMaterialCount] = useState<number | null>(null);
  const [monitor, setMonitor] = useState<{ kind: "loading" } | { kind: "ready"; data: Awaited<ReturnType<typeof getV2MonitorStatus>> } | { kind: "error" }>({ kind: "loading" });
  const [priceSeedState, setPriceSeedState] = useState("");
  async function initializePrices() { if (priceSeedState === "正在初始化行情…") return; setPriceSeedState("正在初始化行情…"); try { const result = await initializeMarketData(symbol); setPriceSeedState(result.inserted_count ? "行情初始化成功，新增行情已自动刷新。" : "初始化完成，但供应商没有返回可保存的行情。"); onPricesInitialized(); } catch (error) { setPriceSeedState(actionMessage(error, "行情初始化失败，请登录个人账户后重试。")); } }
  useEffect(() => {
    const controller = new AbortController();
    setMonitor({ kind: "loading" });
    setList({ kind: "loading" });
    setMaterialCount(null);
    getV2Forecasts({ symbols: symbols.slice(0, MAX_WATCHLIST), limit: 200 }, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setList({ kind: "ready", data }); })
      .catch(() => { if (!controller.signal.aborted) setList({ kind: "error" }); });
    getMaterialLibrary(symbol, { limit: 1, signal: controller.signal })
      .then((library) => { if (!controller.signal.aborted) setMaterialCount(library.total); })
      .catch(() => { /* the count stays a dash */ });
    if (personal) Promise.allSettled([getEarningsJudgments({ limit: 100 }, controller.signal)]).then(([result]) => { if (!controller.signal.aborted) setLane(judgmentLane(result)); });
    else setLane({ lane: "hidden" });
    getV2MonitorStatus(controller.signal).then((data) => { if (!controller.signal.aborted) setMonitor({ kind: "ready", data }); }).catch(() => { if (!controller.signal.aborted) setMonitor({ kind: "error" }); });
    return () => controller.abort();
  }, [symbol, symbols.join(","), personal]);
  const bySymbol = forecastBySymbol(list.kind === "ready" ? list.data.forecasts : []);
  const currentRows = bySymbol.get(symbol.toUpperCase()) ?? [];
  const currentWorkspaceState = list.kind;
  const currentVersion = currentWorkspaceState === "ready" ? currentRows[0] ?? null : null;
  const currentJobs = list.kind === "ready" ? list.data.job_alerts.filter((alert) => alert.symbol === symbol && (alert.status === "queued" || alert.status === "running")).length : 0;
  const currentRecord = researchRecord(symbol, list.kind === "ready" ? list.data.forecasts : [], lane?.lane === "ready" ? lane.judgments : []);
  // 打开预测 goes to the forecast itself; with none, to the home filtered to this stock, where it can be created.
  const openForecast = () => navigate(currentVersion ? paths.forecast(currentVersion.id) : paths.forecasts({ symbol }));
  const currentFilingsList = currentFilings.kind === "ready" ? currentFilings.data.filings : [];
  const officialFilingCount = currentFilings.kind === "ready" ? currentFilingsList.length : null;
  return <section className="workspace-stack overview-workspace">
    <WorkspaceIntro eyebrow={t("研究总览")} title={t("从你的研究队列开始")} description={t("队列汇总独立预测、官方资料和已保存材料。没有预测时仍可上传材料、读取 SEC 原文并开始新研究。")} />
    <section className="overview-focus" aria-label={`${symbol} ${t("当前研究状态")}`}>
      <div><p className="eyebrow">{t("当前股票")} / {symbol}</p><h2>{currentWorkspaceState === "loading" ? t("正在读取研究状态") : currentWorkspaceState === "error" ? t("研究状态暂不可用") : currentVersion ? `${t("预测版本")} ${currentVersion.latest_version_no}` : t("可开始一项新研究")}</h2><p>{currentWorkspaceState === "loading" ? t("正在读取当前预测与研究记录。") : currentWorkspaceState === "error" ? t("当前预测状态读取失败，请稍后重试。") : currentVersion ? `${t("最近决策时间")} ${formatUtc(currentVersion.decision_at)}; ${t("决策模型")} ${currentVersion.decider.actual_model ?? t("未记录")}${currentVersion.target_end_date ? `; ${t("目标日")} ${currentVersion.target_end_date}` : ""}` : t("目前没有当前预测版本。历史行情与材料仍可查看，也可以直接创建预测。")}</p>
        {currentRecord.judgment && <p><a href={appHref(currentRecord.judgment.hash)}>{t(currentRecord.judgment.typeLabel)}</a> · {t(currentRecord.judgment.direction)} · {t(currentRecord.judgment.result)}</p>}
        {currentVersion?.probabilities && <p className="fine-print">{t("概率未经校准，属实验性信息。仅供参考，买不买由你决定。")}</p>}</div>
      <div className="overview-focus-actions"><button className="primary-action" disabled={currentWorkspaceState === "loading"} onClick={openForecast}>{currentWorkspaceState === "loading" ? t("正在读取…") : currentVersion ? t("打开预测") : currentWorkspaceState === "ready" ? t("创建预测") : t("打开预测")}</button><button className="secondary-action" onClick={() => onNavigate("materials")}>{<Tx text={"查看材料库"} />}</button></div>
    </section>
    <section className="overview-metrics" aria-label={t("当前研究状态")}>
      <article><span>{<Tx text={"独立预测数"} />}</span><strong>{list.kind === "ready" ? currentRows.length : "—"}</strong><small>{currentJobs ? `${currentJobs} ${t("项任务处理中")}` : t("按当前预测记录统计")}</small></article>
      <article><span>{<Tx text={"材料总数"} />}</span><strong>{materialCount ?? "—"}</strong><small>{<Tx text={"已保存官方和上传材料"} />}</small></article>
      <article><span>{<Tx text={"SEC 官方材料"} />}</span><strong>{officialFilingCount ?? "—"}</strong><small>{currentFilings.kind === "error" ? t("官方资料目录暂不可用") : t("当前股票已保存的官方文件")}</small></article>
      <article><span>{<Tx text={"监控状态"} />}</span><strong>{monitor.kind === "loading" ? t("正在读取") : monitor.kind === "error" ? t("暂不可用") : t(monitorHealthLabel(monitor.data.health))}</strong><small>{monitor.kind === "loading" ? t("正在读取监控记录") : monitor.kind === "error" ? t("无法读取监控状态") : monitor.data.last_success?.completed_at ? `${t("最近成功")} ${formatUtc(monitor.data.last_success.completed_at)}` : t("尚无成功运行记录")}</small></article>
    </section>
    <section className="universe-section" aria-labelledby="universe-title"><div className="section-heading"><div><p className="eyebrow">{<Tx text={"研究队列"} />}</p><h2 id="universe-title">{<Tx text={"自选股票"} />}</h2></div><span>{<Tx text={"按当前研究数据读取"} />}</span></div><div className="universe-grid">
      {symbols.map((ticker) => {
        const tickerRows = bySymbol.get(ticker.toUpperCase()) ?? [];
        const latest = tickerRows[0] ?? null;
        const isCurrent = ticker === symbol;
        return <article className={`universe-card ${isCurrent ? "is-current" : ""}`} key={ticker}>
          <div className="universe-card-top"><strong>{ticker}</strong>{isCurrent && <span>{<Tx text={"当前"} />}</span>}</div>
          {list.kind === "loading" && <p className="universe-pending">{<Tx text={"正在读取研究状态…"} />}</p>}
          {list.kind === "error" && <p className="universe-error" role="status">{t("暂时无法读取该股票的研究状态。")}</p>}
          {list.kind === "ready" && <><dl><div><dt>{<Tx text={"独立预测"} />}</dt><dd>{tickerRows.length}</dd></div>{isCurrent && <><div><dt>{<Tx text={"材料"} />}</dt><dd>{materialCount ?? "—"}</dd></div><div><dt>{<Tx text={"SEC 官方材料"} />}</dt><dd>{officialFilingCount ?? "—"}</dd></div></>}</dl>
            {latest
              ? <small><a href={hashHref(paths.forecast(latest.id))}>{t("最新版本")} {latest.latest_version_no}</a> · {latest.probabilities ? `${t("下跌")} ${Math.round(latest.probabilities.bearish * 100)}% · ${t("持平")} ${Math.round(latest.probabilities.neutral * 100)}% · ${t("上涨")} ${Math.round(latest.probabilities.bullish * 100)}%` : t(modelStatusLabel(latest.model_status))} · {t("决策模型")} {latest.decider.actual_model ?? t("未记录")}{latest.target_end_date ? ` · ${t("目标日")} ${latest.target_end_date}` : ""}</small>
              : <small>{t("当前没有预测版本")}</small>}</>}
          <div className="watch-card-actions"><button className="universe-open" type="button" onClick={() => onOpenStock(ticker)}>{t("打开")} {ticker} {t("总览")} <span aria-hidden="true">→</span></button><button className="watch-remove" type="button" onClick={() => onRemove(ticker)} aria-label={`${t("从关注列表移除")} ${ticker}`}>×</button></div>
        </article>;
      })}
    </div></section>
    <div className="overview-shortcuts"><button className="text-button" onClick={() => onNavigate("materials")}>{<Tx text={"管理材料 / 扫描 SEC"} />}</button><button className="text-button" onClick={() => onNavigate("evaluation")}>{<Tx text={"查看到期评估"} />}</button><span>{priceError ? `${t("行情暂不可用")}: ${priceError}` : priceHistory?.latest_trading_date ? `${symbol} ${t("行情截至")} ${priceHistory.latest_trading_date}` : t("本地没有可展示的行情")}</span><button className="text-button" type="button" onClick={initializePrices} disabled={priceSeedState === "正在初始化行情…"}>{t("初始化一年行情")}</button>{priceSeedState && <small role="status">{t(priceSeedState)}</small>}</div>
  </section>;
}

export function WorkspacePageHeader({ symbol, section, recordCount, supported }: { symbol: string; section: ResearchSection; recordCount: number | null; supported: boolean }) {
  const { t } = useLocale();
  const title = t(WORKSPACE_SECTION_TITLE[section]);
  return <header className="workspace-heading">
    <div><p className="eyebrow">{symbol} / {title}</p><h1 id="workspace-title">{title}</h1></div>
    <div className="workspace-context"><span className={`live-dot ${supported ? "" : "muted"}`} aria-hidden="true" /><span>{supported ? t("支持新建研究") : t("可查看已有研究")}</span>{recordCount !== null && <span className="workspace-record-count">{recordCount} {t("项独立预测")}</span>}</div>
  </header>;
}

export function WorkspaceIntro({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  const { t } = useLocale();
  return <section className="workspace-intro">
    <div><p className="eyebrow">{t(eyebrow)}</p><h2>{t(title)}</h2><p>{t(description)}</p></div>
    {action && <div className="workspace-intro-action">{action}</div>}
  </section>;
}

export function Loading({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  return <main className="state-card" aria-live="polite" aria-busy="true"><span className="loading-mark" aria-hidden="true" /><p className="kicker">{<Tx text={"公司研究"} />}</p><h1>{t("正在读取")} {symbol} {t("的研究资料")}</h1><p>{<Tx text={"正在读取本地预测、SEC 目录和行情。"} />}</p></main>;
}

export function isSupportedSymbol(symbol: string): symbol is SupportedSymbol { return isValidSymbol(symbol); }
function isValidSymbol(symbol: string): boolean { return /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/i.test(symbol.trim()); }
export function actionMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return translatePhrase(fallback);
  if (error.message.includes("SEC_EDGAR_USER_AGENT")) return translatePhrase("尚未配置 SEC 联系邮箱。请先按 README 配置后重试。");
  return translatePhrase(error.message);
}
function monitorHealthLabel(status: string) {
  if (status === "healthy") return translatePhrase("监控正常");
  if (status === "delayed") return translatePhrase("监控延迟");
  if (status === "degraded") return translatePhrase("监控异常");
  return translatePhrase("尚无记录");
}
function formatDateTime(value: string, locale: "zh-CN" | "en-US" = getLocalePreference()) { return formatLocalizedDateTime(value, locale); }
function formatUtc(value: string) { return formatDateTime(value); }
