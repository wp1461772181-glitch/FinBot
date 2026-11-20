import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { SkeletonRows } from "@/components/state/Skeleton";
import { StatefulButton } from "@/components/state/StatefulButton";
import { useRunningTasks } from "@/components/state/tasks";
import { cn } from "@/lib/utils";
import { createV2ForecastJob, getEarningsJudgments, getV2Forecasts } from "../../../api/forecast-v2";
import { getModelRoles } from "../../../api/catalog-admin";
import { getPortfolio } from "../../../api/portfolio-ledger";
import type { EarningsJudgment, V2ForecastList } from "../../../api/forecast-v2";
import { OPINION_DISCLAIMER } from "../../../data-display.mjs";
import { filterRows, filterScopes, formalRowModel, judgmentLane, judgmentRowModel, sortForAttention, splitDelivered, symbolMark } from "../../../forecast-home.mjs";
import type { ForecastScope, JudgmentLane } from "../../../forecast-home.mjs";
import { hasProbabilities } from "../../../probability-bar.mjs";
import { useLocale } from "../../../i18n";
import { MonitorChip } from "../MonitorChip";
import { actionMessage } from "../support";
import { FormalForecastRow } from "./FormalForecastRow";
import { JudgmentRow } from "./JudgmentRow";
import { SymbolCombobox } from "./SymbolCombobox";
import { TaskStrip } from "./TaskStrip";
import { JOB_TASK_PREFIX, followJob, onJobSettled } from "./jobs";

const SCOPE_LABEL: Record<ForecastScope, string> = { all: "全部", holdings: "持仓", queue: "研究队列" };
type Lane = JudgmentLane<EarningsJudgment>;
type Read<T> = { kind: "loading" } | { kind: "ready"; data: T } | { kind: "error" };
const JUDGMENT_NOTE = "模型意见，未经盲测，仅供参考；买不买由你决定。";

/**
 * 预测首页 (#/research/forecasts, design 4.6): every company's forecasts in two lanes side by side, 正式预测 (20 trading days) and 财报判断 (the first
 * session), each with the one sentence of what it answers.  The two lanes have their own rows (FormalForecastRow, JudgmentRow) and their own errors.  On a
 * phone the lanes are two tabs.  The jobs sit in a strip above the lists.  The company page's 预测 tab shows this page filtered to one company (`embedded`).
 */
export function ForecastHome({ queue, personal, symbolFilter, onClearSymbol, embedded = false }: { queue: string[]; personal: boolean; symbolFilter?: string; onClearSymbol: () => void; embedded?: boolean }) {
  const { t } = useLocale();
  const [list, setList] = useState<Read<V2ForecastList>>({ kind: "loading" });
  const [lane, setLane] = useState<Lane | null>(null);
  const [holdings, setHoldings] = useState<string[] | null>(null);
  const [forecastRole, setForecastRole] = useState<string | null | undefined>(undefined);
  const [scope, setScope] = useState<ForecastScope>("all");
  const [tab, setTab] = useState<"formal" | "judgment">("formal");
  const [reloadKey, setReloadKey] = useState(0);
  const [createSymbol, setCreateSymbol] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const jobRunning = useRunningTasks().some(task => task.id.startsWith(JOB_TASK_PREFIX));

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setList({ kind: "loading" });
    getV2Forecasts({ limit: 200 }, signal)
      .then(next => { if (!signal.aborted) setList({ kind: "ready", data: next }); })
      .catch(() => { if (!signal.aborted) setList({ kind: "error" }); });
    if (personal) {
      Promise.allSettled([getEarningsJudgments({ limit: 100 }, signal)]).then(([result]) => { if (!signal.aborted) setLane(judgmentLane(result)); });
      getPortfolio(signal).then(next => { if (!signal.aborted) setHoldings(next.positions.map(position => position.symbol)); }).catch(() => { if (!signal.aborted) setHoldings(null); });
      getModelRoles(signal).then(next => { if (!signal.aborted) setForecastRole(next.roles.forecast ?? null); }).catch(() => { if (!signal.aborted) setForecastRole(undefined); });
    } else {
      setLane({ lane: "hidden" });
      setHoldings(null);
    }
    return () => controller.abort();
  }, [personal, reloadKey]);

  // A job that ends makes a version (or does not): the lists are read again either way, so the new row is there.
  useEffect(() => onJobSettled(() => setReloadKey(value => value + 1)), []);

  const scopes = filterScopes(holdings !== null);
  const activeScope = scopes.includes(scope) ? scope : "all";
  const heldSymbols = holdings ?? [];
  const ready = list.kind === "ready" ? list.data : null;
  const rows = useMemo(() => {
    if (!ready) return [];
    const bySymbol = symbolFilter ? ready.forecasts.filter(row => row.symbol === symbolFilter) : ready.forecasts;
    return filterRows(bySymbol, activeScope, heldSymbols, queue);
  }, [ready, symbolFilter, activeScope, heldSymbols, queue]);
  const sorted = useMemo(() => sortForAttention(rows, ready?.job_alerts ?? [], new Date()), [rows, ready]);
  const judgments = useMemo(() => {
    if (lane?.lane !== "ready") return [];
    const bySymbol = symbolFilter ? lane.judgments.filter(item => item.symbol === symbolFilter) : lane.judgments;
    return filterRows(bySymbol, activeScope, heldSymbols, queue);
  }, [lane, symbolFilter, activeScope, heldSymbols, queue]);
  const { delivered, skipped } = splitDelivered(judgments);
  const choices = useMemo(() => [...new Set([...queue, ...heldSymbols])].sort(), [queue, heldSymbols]);
  const showJudgments = personal && lane?.lane !== "hidden";
  const symbol = createSymbol && choices.includes(createSymbol) ? createSymbol : choices[0] ?? "";
  const withBars = sorted.some(({ row }) => hasProbabilities(row.probabilities));

  async function createForecast(target?: string) {
    const chosen = target ?? symbol;
    if (!chosen) return;
    setActionError(null);
    const job = await createV2ForecastJob(chosen);
    followJob(job, `${t("创建预测")} · ${chosen}`);
  }
  const create = (target?: string) => createForecast(target).catch(error => { setActionError(actionMessage(error, "无法创建预测任务。")); });

  const Heading = embedded ? "h2" : "h1";
  const Root = embedded ? "section" : "main";
  const laneClass = (id: "formal" | "judgment") => cn("min-w-0 flex-col gap-3", tab === id ? "flex" : "hidden", "lg:flex");
  return <Root data-testid="forecast-home" aria-labelledby="forecast-home-title" className={cn("flex min-w-0 flex-col gap-4", !embedded && "mx-auto w-full max-w-[1280px] flex-1 p-4 lg:p-6 text-[length:medium] leading-[normal]")}>
    <header className="flex flex-wrap items-start gap-x-4 gap-y-3">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <Heading id="forecast-home-title" className="text-title-m text-ink">{t("预测")}</Heading>
        <div role="group" aria-label={t("筛选")} className="flex flex-wrap items-center gap-1">
          {scopes.map(item => <button key={item} type="button" data-testid={`scope-${item}`} aria-pressed={item === activeScope} onClick={() => setScope(item)}
            className={cn("inline-flex h-8 items-center rounded-sm border px-3 text-small outline-none focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11 cursor-pointer appearance-auto py-px", item === activeScope ? "border-brand bg-brand-soft font-medium text-ink" : "border-line bg-surface text-ink-2 hover:bg-sunken")}>{t(SCOPE_LABEL[item])}</button>)}
          {symbolFilter && <button type="button" data-testid="symbol-chip" onClick={onClearSymbol} aria-label={`${t("清除公司筛选")} ${symbolFilter}`} className="inline-flex h-8 items-center gap-1 rounded-sm border border-line-strong bg-sunken px-2 font-mono text-small text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11 cursor-pointer appearance-auto py-px">{symbolFilter}<X aria-hidden="true" className="size-3.5" /></button>}
        </div>
      </div>
      <div className="ml-auto flex min-w-0 flex-col items-end gap-1.5">
        <div className="flex flex-wrap items-center justify-end gap-2">
          <MonitorChip />
          {personal && choices.length > 0 && <div data-testid="forecast-create" className="flex items-center gap-2">
            <SymbolCombobox value={symbol} choices={choices} onChange={setCreateSymbol} />
            <StatefulButton type="button" data-testid="forecast-create-go" disabled={jobRunning} onClick={() => create()}>{jobRunning ? t("任务处理中…") : t("创建预测")}</StatefulButton>
          </div>}
        </div>
        {personal && choices.length > 0 && forecastRole !== undefined && <small data-testid="forecast-next-model" className="text-caption text-muted-foreground">{forecastRole ? <>{t("下一次预测使用：")}{forecastRole}</> : t("下一次预测使用：服务器默认模型（设置中未绑定预测模型）")}</small>}
      </div>
    </header>

    <TaskStrip alerts={ready?.job_alerts} onRetry={target => void create(target)} />
    {actionError && <ErrorBar message={actionError} />}

    {showJudgments && <div role="tablist" aria-label={t("预测类型")} className="flex gap-1 border-b border-line lg:hidden">
      {(["formal", "judgment"] as const).map(id => <button key={id} type="button" role="tab" id={`lane-tab-${id}`} data-testid={`lane-tab-${id}`} aria-selected={tab === id} aria-controls={`lane-${id}`} tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)}
        onKeyDown={event => { if (event.key === "ArrowRight" || event.key === "ArrowLeft") { event.preventDefault(); const next = id === "formal" ? "judgment" : "formal"; setTab(next); document.getElementById(`lane-tab-${next}`)?.focus(); } }}
        className={cn("-mb-px min-h-11 border-x-0 border-t-0 border-b-2 bg-transparent px-4 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer appearance-auto py-px", tab === id ? "border-brand font-medium text-ink" : "border-transparent text-muted-foreground")}>
        {id === "formal" ? t("正式预测") : t("财报判断")}<span className="ml-1.5 font-mono text-caption text-muted-foreground">{id === "formal" ? sorted.length : lane?.lane === "ready" ? delivered.length : 0}</span>
      </button>)}
    </div>}

    <div className={cn("grid items-start gap-6", showJudgments && "lg:grid-cols-2")}>
      <section id="lane-formal" role={showJudgments ? "tabpanel" : undefined} aria-labelledby={showJudgments ? "lane-tab-formal" : undefined} data-testid="lane-formal" data-slot="forecast-lane" className={showJudgments ? laneClass("formal") : "flex min-w-0 flex-col gap-3"}>
        <div className="flex flex-col gap-1">
          <h2 className="text-title-s text-ink">{t("正式预测")}</h2>
          <p className="text-small text-muted-foreground">{t("正式预测看 20 个交易日，给出下跌、持平、上涨三类概率。")}</p>
        </div>
        {list.kind === "loading" && <SkeletonRows rows={4} />}
        {list.kind === "error" && <ErrorBar message={t("暂时无法读取预测日期列表。")} onRetry={() => setReloadKey(value => value + 1)} />}
        {ready && sorted.length === 0 && (symbolFilter || activeScope !== "all"
          ? <p className="text-small text-muted-foreground">{t("没有符合筛选条件的预测。")}</p>
          : <EmptyState title={t("还没有预测")} description={t("创建第一项预测后会出现在这里。")} action={personal && choices.length > 0 ? { label: t("创建第一项预测"), onClick: () => void create() } : undefined} className="rounded-md border border-dashed border-line" />)}
        {sorted.length > 0 && <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {sorted.map(({ row, tier }) => <FormalForecastRow key={row.id} model={formalRowModel(row, { holdings: heldSymbols, queue })} tier={tier} />)}
        </ul>}
      </section>

      {showJudgments && <section id="lane-judgment" role="tabpanel" aria-labelledby="lane-tab-judgment" data-testid="lane-judgment" data-slot="forecast-lane" className={laneClass("judgment")}>
        <div className="flex flex-col gap-1">
          <h2 className="text-title-s text-ink">{t("财报判断")}</h2>
          <p className="text-small text-muted-foreground">{t("财报判断只看发布后的首个交易日，不是概率预测。")}</p>
        </div>
        {lane === null && <SkeletonRows rows={3} />}
        {lane?.lane === "error" && <ErrorBar message={t("财报判断暂时无法读取。")} onRetry={() => setReloadKey(value => value + 1)} />}
        {lane?.lane === "ready" && delivered.length === 0 && skipped.length === 0 && <EmptyState title={t("还没有财报判断")} description={t("公司发布财报后，如果判断发送给你，会出现在这里。")} className="rounded-md border border-dashed border-line" />}
        {delivered.length > 0 && <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {delivered.map(item => <JudgmentRow key={item.id} model={judgmentRowModel(item)} mark={symbolMark(item.symbol, heldSymbols, queue)} />)}
        </ul>}
        {skipped.length > 0 && <details data-testid="judgments-skipped" className="rounded-md border border-line bg-surface">
          <summary className="cursor-pointer px-3 py-2 text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("未发送")} {skipped.length} {t("条")}</summary>
          <ul className="m-0 flex list-none flex-col gap-2 p-2">
            {skipped.map(item => <JudgmentRow key={item.id} model={judgmentRowModel(item)} mark={symbolMark(item.symbol, heldSymbols, queue)} />)}
          </ul>
        </details>}
        {delivered.length + skipped.length > 0 && <p data-testid="judgment-lane-note" className="material-opinion-footnote">{t(JUDGMENT_NOTE)}</p>}
      </section>}
    </div>
    {withBars && <p data-testid="forecast-disclaimer" className="material-opinion-footnote">{t(OPINION_DISCLAIMER)}</p>}
  </Root>;
}
