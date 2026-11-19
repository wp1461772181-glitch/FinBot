import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ArrowLeft } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { OpinionCard } from "@/components/OpinionCard";
import { SourceCard, SourceQuote } from "@/components/SourceCard";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonCard } from "@/components/state/Skeleton";
import { StatefulButton } from "@/components/state/StatefulButton";
import { useRunningTasks } from "@/components/state/tasks";
import { cn } from "@/lib/utils";
import { ApiError } from "../../../api/base";
import { createV2ForecastJob, getEarningsJudgment, getV2Forecasts } from "../../../api/forecast-v2";
import type { EarningsJudgment, V2ForecastListRow } from "../../../api/forecast-v2";
import { judgmentRowModel, promotionRequest, promotionState } from "../../../forecast-home.mjs";
import { NOT_RECORDED } from "../../../forecast-model.mjs";
import { Parts } from "../../../ForecastShared";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { actionMessage } from "../support";
import { TaskStrip } from "./TaskStrip";
import { JOB_TASK_PREFIX, followJob, onJobSettled } from "./jobs";
import { day } from "./format";

const JUDGMENT_NOTE = "模型意见，未经盲测，仅供参考；买不买由你决定。";
const PROMOTION_REASON: Record<string, string> = {
  first_session_open: "首个交易日收盘后可用",
  filing_not_in_library: "这份财报还没进资料库，先到材料库扫描",
};

/**
 * 财报判断 (#/research/judgments/:eventId, design 4.6): one earnings judgment as a card on the opinion material (direction, result, the after-hours
 * move it knew, the model; its footnote is the page's one disclaimer), the reasons with the quotes they rest on (each quote a fact block in the quote face),
 * the counter-argument, and what can be done with the filing: start a formal forecast from it, or revise the open one with it.  A judgment is a different
 * kind of record from a formal forecast, so it shows no probabilities and no versions.
 */
export function JudgmentPage({ judgmentId }: { judgmentId: string }) {
  const { t } = useLocale();
  const [state, setState] = useState<{ kind: "loading" } | { kind: "ready"; data: EarningsJudgment } | { kind: "error"; status: number | null }>({ kind: "loading" });
  const [forecasts, setForecasts] = useState<V2ForecastListRow[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const jobRunning = useRunningTasks().some(task => task.id.startsWith(JOB_TASK_PREFIX));

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    getEarningsJudgment(judgmentId, controller.signal)
      .then(judgment => { if (!controller.signal.aborted) setState({ kind: "ready", data: judgment }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setState({ kind: "error", status: error instanceof ApiError ? error.status ?? null : null }); });
    return () => controller.abort();
  }, [judgmentId]);

  const symbol = state.kind === "ready" ? state.data.symbol : null;
  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    getV2Forecasts({ symbols: [symbol], state: "open", limit: 5 }, controller.signal)
      .then(next => { if (!controller.signal.aborted) setForecasts(next.forecasts); })
      .catch(() => { if (!controller.signal.aborted) setForecasts([]); });
    return () => controller.abort();
  }, [symbol, reloadKey]);
  // A forecast started from here ends, with a version or without one: the open forecast is read again.
  useEffect(() => onJobSettled(() => setReloadKey(value => value + 1)), []);

  const frame = (children: React.ReactNode) => <main data-testid="judgment-page" aria-labelledby="judgment-title" className="mx-auto flex w-full max-w-[880px] flex-1 flex-col gap-4 p-4 lg:p-6">{children}</main>;
  if (state.kind === "loading") return frame(<DelayedSkeleton><SkeletonCard /><SkeletonCard /></DelayedSkeleton>);
  if (state.kind === "error") {
    const ownerOnly = state.status === 401 || state.status === 403;
    return frame(<EmptyState title={t(ownerOnly ? "登录个人账户后才能查看财报判断" : state.status === 404 ? "找不到这项财报判断" : "财报判断暂时无法读取。")} action={{ label: t("回到预测首页"), to: paths.forecasts() }} />);
  }
  const judgment = state.data;
  const model = judgmentRowModel(judgment);
  const openForecast = forecasts[0] ?? null;
  const promotion = promotionState(judgment, openForecast);
  const request = promotionRequest(judgment);
  const create = async () => {
    if (!request) return;
    setActionError(null);
    const job = await createV2ForecastJob(request.symbol, request.source_refs);
    followJob(job, `${t("创建预测")} · ${request.symbol}`);
  };
  const reviseHref = promotion.state === "revise" && openForecast && judgment.filing_source_id ? paths.forecast(openForecast.id, { revise: judgment.filing_source_id }) : null;
  return frame(<>
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Link to={paths.forecasts()} data-testid="judgment-back" className="inline-flex h-8 items-center gap-1 rounded-sm text-small text-ink-2 outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11 underline"><ArrowLeft aria-hidden="true" className="size-4" />{t("预测")}</Link>
      <h1 id="judgment-title" className="min-w-0 text-title-m text-ink mb-[0.67em]"><span className="font-mono">{judgment.symbol}</span> · {t("财报判断")}</h1>
    </header>
    <TaskStrip />
    {!judgment.delivered && <p role="status" className="text-small text-ink-2 mb-[1em]">{t("这条判断没有发送给你。")}</p>}

    <OpinionCard data-testid="judgment-card" model={judgment.model} time={day(judgment.accepted_at)} footnote={<p data-testid="judgment-disclaimer">{t(JUDGMENT_NOTE)}</p>}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p data-testid="judgment-direction" className="text-title-m text-ink">{t(model.direction)}</p>
        {model.confidence && <StatusBadge kind="opinion">{t(model.confidence)}</StatusBadge>}
        <span className="text-caption text-muted-foreground">{t(model.typeLabel)}</span>
      </div>
      <p className="text-small text-ink-2">{t(model.typeNote)}</p>
      <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-1.5 text-small">
        <dt className="text-muted-foreground">{t("结果")}</dt><dd className="m-0 text-ink">{t(model.result)}</dd>
        {model.afterHours && <><dt className="text-muted-foreground">{t("盘后走势")}</dt><dd className="m-0 font-mono tabular-nums text-ink"><Parts parts={model.afterHours.parts} /></dd></>}
        <dt className="text-muted-foreground">{t("决策模型")}</dt><dd className="m-0 text-ink [overflow-wrap:anywhere]"><span className="font-mono">{model.model ?? t(NOT_RECORDED)}</span>{model.modelFirstStage ? ` (${t("首条消息时的模型")})` : ""}</dd>
        <dt className="text-muted-foreground">{t("财报发布时间")}</dt><dd className="m-0 font-mono tabular-nums text-ink">{day(judgment.accepted_at)}</dd>
        {(judgment.source_url || judgment.filing_source_id) && <><dt className="text-muted-foreground">{t("原文")}</dt><dd className="m-0 flex flex-wrap gap-x-4 gap-y-1">
          {judgment.source_url && <a href={judgment.source_url} target="_blank" rel="noopener noreferrer" className="text-brand underline-offset-2 hover:underline">{t("打开原始来源")}</a>}
          {judgment.filing_source_id && <Link to={paths.materials({ symbol: judgment.symbol, focus: judgment.filing_source_id, type: "official_filing" })} data-testid="judgment-material-link" className="text-brand underline-offset-2 hover:underline">{t("在材料库中查看这份财报")}</Link>}
        </dd></>}
      </dl>
    </OpinionCard>

    <section data-testid="judgment-reasons" aria-labelledby="judgment-reasons-title" className="flex min-w-0 flex-col gap-3">
      <h2 id="judgment-reasons-title" className="text-title-s text-ink mb-[0.83em]">{t("理由（附原文）")}</h2>
      {judgment.reasons.length === 0 ? <p className="text-small text-muted-foreground mb-[1em]">{t(NOT_RECORDED)}</p> : <ol className="m-0 flex list-none flex-col gap-4 p-0">
        {judgment.reasons.map((reason, index) => <li key={index} className="flex min-w-0 flex-col gap-2">
          <p className="text-body text-ink [overflow-wrap:anywhere] mb-[1em]">{reason.text}</p>
          <SourceCard ordinal={index + 1} title={t("财报原文摘录")} meta={[judgment.accession]} openLabel={t("打开原始来源")}><SourceQuote>“{reason.quote}”</SourceQuote></SourceCard>
        </li>)}
      </ol>}
    </section>
    {judgment.counter_argument && <section data-testid="judgment-counter" aria-labelledby="judgment-counter-title" className="flex min-w-0 flex-col gap-2">
      <h2 id="judgment-counter-title" className="text-title-s text-ink mb-[0.83em]">{t("反方")}</h2>
      <p className="text-body text-ink [overflow-wrap:anywhere] mb-[1em]">{judgment.counter_argument}</p>
    </section>}

    <section data-testid="judgment-actions" aria-labelledby="judgment-actions-title" className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-4">
      <h2 id="judgment-actions-title" className="text-title-s text-ink mb-[0.83em]">{t("基于这份财报")}</h2>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <StatefulButton type="button" data-testid="judgment-create" disabled={promotion.state !== "create" || jobRunning} onClick={create} onError={error => setActionError(actionMessage(error, "无法创建预测任务。"))}>{jobRunning && promotion.state === "create" ? t("任务处理中…") : t("基于这份财报创建正式预测")}</StatefulButton>
          {promotion.state === "revise" && <span className="max-w-64 text-caption text-muted-foreground">{t("这家公司已有进行中的预测，请改用「用这份财报修订」。")}</span>}
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          {reviseHref
            ? <Link to={reviseHref} data-testid="judgment-revise" className={cn(buttonVariants({ variant: "outline" }), "text-ink no-underline hover:text-ink")}>{t("用这份财报修订")}</Link>
            : <Button type="button" variant="outline" data-testid="judgment-revise" disabled>{t("用这份财报修订")}</Button>}
          {promotion.state === "create" && <span className="max-w-64 text-caption text-muted-foreground">{t("这家公司没有进行中的预测可以修订。")}</span>}
        </div>
      </div>
      {promotion.state === "unavailable" && promotion.reason && <p role="status" className="text-small text-ink-2 mb-[1em]">
        {t(PROMOTION_REASON[promotion.reason])}
        {promotion.reason === "filing_not_in_library" && <> · <Link to={paths.materials({ symbol: judgment.symbol })} className="text-brand underline-offset-2 hover:underline underline">{t("打开资料库")}</Link></>}
      </p>}
      {promotion.state !== "unavailable" && <p className="text-caption text-muted-foreground mb-[1em]">{t("新预测只从这份财报的原文出发，不带这条判断的方向和理由。")}</p>}
      {actionError && <ErrorBar message={actionError} />}
    </section>

    {openForecast && <p className="text-small text-muted-foreground mb-[1em]">
      {t("两者问题不同：财报判断看首个交易日，正式预测看 20 个交易日。")} <Link to={paths.forecast(openForecast.id)} data-testid="judgment-open-forecast" className="text-brand underline-offset-2 hover:underline underline">{t("查看这家公司的正式预测")}</Link>
    </p>}
  </>);
}
