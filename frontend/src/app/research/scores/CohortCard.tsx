import { StatTile } from "@/components/StatTile";
import { StatusBadge } from "@/components/StatusBadge";
import type { V2ModelEvaluationCohort } from "../../../types";
import { useLocale, colon, comma } from "../../../i18n";
import { BASELINE_EXPLAINER, BASELINE_NAME, cohortStatusPhrase, cohortView, modelStatusPhrase, timeModePhrase, type Bars } from "./scores-model.mjs";

/** One metric of the comparison: the model's bar and the baseline's, both from zero on the same scale, with their numbers; the sentence is for a screen reader. */
function Metric({ label, model, baseline, bars }: { label: string; model: number | null; baseline: number | null; bars: Bars }) {
  const { t } = useLocale();
  const fixed = (value: number | null) => (value === null ? "—" : value.toFixed(3));
  const row = (name: string, value: number | null, width: number | undefined, tone: string) => <div className="grid grid-cols-[minmax(0,1fr)_3.5rem] items-center gap-x-2 gap-y-0.5 text-small sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3.5rem]">
    <span className="col-span-2 min-w-0 text-ink-2 sm:col-span-1 sm:truncate" title={name}>{name}</span>
    <span aria-hidden="true" className="h-2 min-w-0 overflow-hidden rounded-full bg-sunken"><span className={`block h-full rounded-full ${tone}`} style={{ width: `${width ?? 0}%` }} /></span>
    <span className="text-right font-mono tabular-nums text-ink">{fixed(value)}</span>
  </div>;
  return <div data-testid="score-compare" data-metric={label} role="img" aria-label={`${label}${colon()}${t("模型")} ${fixed(model)}${comma()}${t("同题基准")} ${BASELINE_NAME} ${fixed(baseline)}`} className="flex min-w-0 flex-col gap-1.5">
    <p className="m-0 text-caption font-medium text-muted-foreground">{label}</p>
    {row(t("模型"), model, bars?.model, "bg-brand")}
    {row(`${t("同题基准")} ${BASELINE_NAME}`, baseline, bars?.baseline, "bg-muted-foreground")}
  </div>;
}

/** One model cohort (design 4.8): its four numbers, and under them the comparison with the same-question baseline when the cohort has reached the floor. */
export function CohortCard({ cohort, minimumScoredRoots }: { cohort: V2ModelEvaluationCohort; minimumScoredRoots: number }) {
  const { t, locale } = useLocale();
  const view = cohortView(cohort, minimumScoredRoots);
  const { sample } = view;
  const tile = (metric: string, label: string, value: string | null, footnote: string) => <div data-metric={metric} className="min-w-0 [&>*]:h-full">
    <StatTile label={label} value={value ?? t("样本不足")} footnote={footnote} />
  </div>;
  const floorNote = `${t("已评分的独立预测达到下限后才显示平均值")} · ${sample.scored_root_count}/${minimumScoredRoots}`;
  const scoredOnly = t("仅已成功评分的版本");
  return <article data-testid="cohort-card" data-status={cohort.status} className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-4">
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
      <div className="min-w-0 flex-1">
        <p className="m-0 text-caption text-muted-foreground">{t(timeModePhrase(cohort.time_mode))} · {t(modelStatusPhrase(cohort.model_status))}{cohort.control ? ` · ${t("已停用的对照")}` : ""}</p>
        <h3 className="m-0 font-mono text-body font-medium text-ink [overflow-wrap:anywhere]">{cohort.provider} / {cohort.actual_model}</h3>
      </div>
      <StatusBadge kind="neutral">{t(cohortStatusPhrase(cohort.status))}</StatusBadge>
    </div>
    <p className="m-0 text-caption text-muted-foreground">{t("问题版本")}: {cohort.question_version ?? t("未记录")} · {t("样本按同组最高版本计数")}</p>
    {view.banner && <p role="status" data-testid="score-banner" className="m-0 rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2">{t(view.banner)}</p>}
    <div data-testid="cohort-numbers" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tile("samples", t("独立预测样本"), String(sample.root_denominator), t("同组代表记录"))}
      {tile("scored", t("已标注 / 已评分"), `${sample.labelled_root_count} / ${sample.scored_root_count}`, `${sample.unscored_root_count} ${t("条尚未评分")}`)}
      {tile("brier", t("平均 Brier"), view.available ? view.brier ?? t("无可用分数") : null, view.available ? scoredOnly : floorNote)}
      {tile("logloss", t("平均 Log loss"), view.available ? view.logLoss ?? t("无可用分数") : null, view.available ? scoredOnly : floorNote)}
    </div>
    {view.comparison && <section data-testid="score-comparison" aria-label={t("与同题基准对比")} className="flex min-w-0 flex-col gap-3 border-t border-line pt-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><h4 className="m-0 text-small font-medium text-ink">{t("与同题基准对比")}</h4><span className="text-caption text-muted-foreground">{t("数值越低越好")}</span></div>
      <div className="grid min-w-0 gap-4 md:grid-cols-2">
        <Metric label={t("模型平均 Brier")} model={view.comparison.brier.model} baseline={view.comparison.brier.baseline} bars={view.comparison.brier.bars} />
        <Metric label={t("模型平均 Log loss")} model={view.comparison.logLoss.model} baseline={view.comparison.logLoss.baseline} bars={view.comparison.logLoss.bars} />
      </div>
      <p className="m-0 text-caption text-muted-foreground">{t("可比较的独立预测")} {view.comparison.pairedRootCount} · {view.comparison.baselineUnavailableRootCount > 0 ? `${view.comparison.baselineUnavailableRootCount} ${t("条缺少基准输入，未计入比较")}` : t("模型与基准在同一批预测上比较")}{locale === "en-US" ? ". " : "。"}{t(BASELINE_EXPLAINER)}</p>
    </section>}
  </article>;
}
