import { StatTile } from "@/components/StatTile";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonCard } from "@/components/state/Skeleton";
import type { V2EvaluationVersion, V2VersionDetail } from "../../../types";
import { useLocale } from "../../../i18n";
import { BriefSection } from "../forecasts/BriefSection";
import { JudgmentBlock } from "../forecasts/JudgmentBlock";
import { day } from "../forecasts/format";
import type { Read } from "../use-read";
import { ReplayMaterials } from "./ReplayMaterials";
import { directionPhrase, evaluationPhrase, jobStatusPhrase, modelPhrase } from "./replay-model.mjs";

/**
 * One replay (design 4.8): the decision day and the target; the model's call as the opinion material (its probabilities are the shared three-class bar, and the page's
 * one disclaimer is that card's footnote); what really happened as fact tiles (the evaluation, the real direction, the scores); the research brief; the material scope.
 * Everything the old detail held is here.  The brief's links open the material library on that analysis, as the old buttons did.
 */
export function ReplayDetail({ symbol, evaluation, read, onRetry }: { symbol: string; evaluation: V2EvaluationVersion | null; read: Read<V2VersionDetail>; onRetry: () => void }) {
  const { t } = useLocale();
  if (read.kind === "loading") return <DelayedSkeleton><div className="flex flex-col gap-4"><SkeletonCard /><SkeletonCard /></div></DelayedSkeleton>;
  if (read.kind === "error") return <ErrorBar message={t("暂时无法读取这条回放详情。")} onRetry={onRetry} />;
  const version = read.value;
  const result = evaluation?.latest_evaluation ?? null;
  const targetEnd = String(version.target_contract.target_end_date ?? t("未知"));
  const none = t("尚无结果");
  return <div data-testid="replay-detail" data-version={version.id} className="flex min-w-0 flex-col gap-4">
    <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <div className="min-w-0 flex-1"><p className="m-0 text-caption text-muted-foreground">{t("历史回放详情")} · <span className="font-mono">{version.symbol || symbol}</span></p><h2 id="replay-detail-title" className="text-title-m text-ink">{t("决策日")} {day(version.decision_at)}</h2></div>
      <span className="text-small text-ink-2">{t("目标截止")} <span className="font-mono tabular-nums">{targetEnd}</span></span>
    </header>
    {version.research_brief && <p data-testid="replay-warning" className="m-0 rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2">{t("回放输入可能含有当时之后才被系统获取的材料。页面会保留材料发布时间与实际获取时间；该预测用于研究复盘，不代表当时真实可得的信息。")}</p>}
    <JudgmentBlock version={version} />
    <section data-testid="replay-result" aria-label={t("到期评估")} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile label={t("预测模型状态")} value={<span className="font-sans text-body">{t(modelPhrase(version.model_status))}</span>} footnote={`${t("任务")}：${t(jobStatusPhrase("succeeded"))}`} />
      <StatTile label={t("到期评估")} value={<span className="font-sans text-body">{t(evaluationPhrase(result?.status ?? "pending"))}</span>} footnote={result?.label_available_at ? `${t("实际结果于")} ${day(result.label_available_at)} ${t("可用")}` : t("等待或无法取得目标期价格")} />
      <StatTile label={t("真实走势")} value={<span className="font-sans text-body">{result?.actual_label ? t(directionPhrase(result.actual_label)) : none}</span>} footnote={result?.actual_target_close != null ? `${t("目标期收盘价")} $${result.actual_target_close.toFixed(2)}` : t("暂无可用收盘价")} />
      <StatTile label="Brier / Log loss" value={<span className="text-title-s">{result?.brier_score != null || result?.log_loss != null ? `${result?.brier_score != null ? result.brier_score.toFixed(4) : none} / ${result?.log_loss != null ? result.log_loss.toFixed(4) : none}` : none}</span>} footnote={t("只在可计算时显示")} />
    </section>
    {version.research_brief && <BriefSection version={version} brief={version.research_brief} citeTarget="materials" />}
    <ReplayMaterials version={version} />
  </div>;
}
