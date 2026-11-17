import { DelayedSkeleton, SkeletonCard } from "@/components/state/Skeleton";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { getV2Evaluations } from "../../../api/forecast-v2";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { actionMessage } from "../support";
import { useRead } from "../use-read";
import { CohortCard } from "./CohortCard";
import { RULE_TEXT, cohortGroups, cohortKey } from "./scores-model.mjs";

/**
 * 模型成绩 (#/research/scores, design 4.8): every company together, because the 30-sample rule means nothing per company.  One card per model cohort: four numbers
 * and the comparison with the same-question baseline.  Scores are marks given afterwards to what a model said (a fact), so the cards are the neutral surface, not the
 * opinion material.  The rule (30 scored independent forecasts) is one line away, folded under the title.
 */
export function ScoresPage() {
  const { t } = useLocale();
  const [read, retry] = useRead("scores", signal => getV2Evaluations(undefined, signal));
  const data = read.kind === "ready" ? read.value : null;
  const cohorts = data?.model_cohorts ?? [];
  return <main data-testid="scores-page" aria-labelledby="scores-title" className="mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6">
    <header className="flex min-w-0 flex-col gap-1">
      <p className="text-caption text-muted-foreground">{t("到期评估")}</p>
      <h1 id="scores-title" className="text-title-m text-ink">{t("模型成绩")}</h1>
      <p className="m-0 max-w-3xl text-small text-ink-2">{t("每组只统计同一时间模式、模型、服务方和问题版本的代表版本。未到期样本显示为待评，不混入其他模型的指标。")}</p>
      <details data-testid="scores-rule" className="max-w-3xl">
        <summary className="inline-flex min-h-8 cursor-pointer items-center text-small font-medium text-brand outline-none focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11">{t("评分规则")}</summary>
        <p className="m-0 pt-1 text-small text-ink-2">{t(RULE_TEXT)}</p>
      </details>
    </header>
    {read.kind === "loading" && <DelayedSkeleton><div className="flex flex-col gap-4"><SkeletonCard /><SkeletonCard /></div></DelayedSkeleton>}
    {read.kind === "error" && <ErrorBar message={actionMessage(read.error, "暂时无法读取到期评估。")} onRetry={retry} />}
    {data && (cohorts.length === 0
      ? <div data-testid="scores-empty"><EmptyState title={data.model_cohorts ? t("还没有模型分组评估") : t("模型分组数据暂不可用")} description={t("这里不会用旧版离线报告或跨模型混合分组填补。预测到期并获得可用行情后，结果会进入对应模型组。")} action={{ label: t("去预测首页"), to: paths.forecasts() }} /></div>
      : cohortGroups(cohorts).map(group => <section key={group.key} data-testid="cohort-group" data-group={group.key} aria-labelledby={`cohort-group-${group.key}`} className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-col gap-0.5"><h2 id={`cohort-group-${group.key}`} className="text-title-s text-ink">{t(group.title)}</h2><p className="m-0 text-caption text-muted-foreground">{t(group.note)}</p></div>
        {group.items.map((cohort, index) => <CohortCard key={cohortKey(cohort, index)} cohort={cohort} minimumScoredRoots={data.minimum_scored_roots} />)}
      </section>))}
  </main>;
}
