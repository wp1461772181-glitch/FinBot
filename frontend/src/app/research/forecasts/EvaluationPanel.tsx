import type { ReactNode } from "react";
import { ErrorBar } from "@/components/state/ErrorBar";
import { SkeletonCard } from "@/components/state/Skeleton";
import type { V2EvaluationCohort, V2EvaluationResponse, V2EvaluationRoot, V2ModelEvaluationCohort, V2VersionDetail } from "../../../types";
import { BASELINE_NAME, forecastCopy, hasDecisionProbabilities } from "../../../forecast-model.mjs";
import { asRecord, asText } from "../../../ForecastShared";
import type { ResourceState } from "../../../ForecastShared";
import { translatePhrase, useLocale } from "../../../i18n";
import { day } from "./format";

function Block({ aria, label, title, sub, children }: { aria?: string; label: string; title: string; sub?: ReactNode; children?: ReactNode }) {
  return <section data-testid="forecast-evaluation" aria-label={aria} className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-col gap-1">
      <p className="text-caption font-medium text-muted-foreground mb-[1em]">{label}</p>
      <h3 className="text-title-s text-ink mb-[1em]">{title}</h3>
      {sub && <p className="text-small text-ink-2 [overflow-wrap:anywhere] mb-[1em]">{sub}</p>}
    </div>
    {children}
  </section>;
}
function Sample({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="material-fact flex flex-col gap-0.5 px-3 py-2"><span className="text-caption text-muted-foreground">{label}</span><strong className="font-mono text-small font-medium tabular-nums text-ink">{value}</strong><small className="text-caption text-muted-foreground">{note}</small></div>;
}
const Note = ({ children }: { children: ReactNode }) => <p className="text-caption text-muted-foreground [overflow-wrap:anywhere] mb-[1em]">{children}</p>;

/**
 * 到期评估 (the old 到期评估 readout, same reading rules): only saved results are shown, nothing is fetched or computed here.  For a version with
 * probabilities the result comes from the cohort of the same provider, model and question version (a mixed cohort never stands in); an older version
 * reads the root's own cohort.  A forecast whose target has not come says 目标未到期 · 待评估.
 */
export function EvaluationPanel({ evaluations, selectedRootId, selectedVersionId, selectedVersionDetail }: { evaluations: ResourceState<V2EvaluationResponse>; selectedRootId: string; selectedVersionId: string; selectedVersionDetail: V2VersionDetail | null }) {
  const { locale, t } = useLocale();
  if (evaluations.kind === "loading") return <SkeletonCard />;
  if (evaluations.kind === "error") return <ErrorBar message={evaluations.message} />;
  if (selectedVersionDetail && hasDecisionProbabilities(selectedVersionDetail.model_status)) {
    const modelCohort = modelEvaluationCohort(evaluations.data, selectedVersionDetail);
    const decisionProvider = asRecord(selectedVersionDetail.model_manifest.decision_provider);
    const copy = forecastCopy({ model_status: selectedVersionDetail.model_status, provider: asText(decisionProvider.provider), actual_model: asText(decisionProvider.actual_model) });
    if (!modelCohort) return <Block label={t(copy.evalLabel)} title={t(evaluations.data.model_cohorts ? "尚无匹配的模型分组" : "模型分组评估尚不可用")} sub={t(evaluations.data.model_cohorts ? copy.evalNoMatchBody : "API 尚未提供按模型隔离的评估分组；为避免混淆样本分母，不使用旧的混合分组代替。")} />;
    const root = modelCohort.roots.find(item => item.root_id === selectedRootId);
    const representative = root?.versions[0];
    const representsSelected = representative?.id === selectedVersionId;
    const evaluation = representsSelected ? representative?.latest_evaluation ?? null : null;
    const state = evaluationStateText(evaluation?.status, root?.target_end_date ?? null);
    const scoreParts = scoresOf(evaluation, t);
    return <Block aria={t(copy.evalAria)} label={t(copy.evalLabel)} title={representsSelected ? state : t("显示该独立预测的最新代表版本")} sub={`${t("模型")} ${modelCohort.actual_model} · ${t("问题")} ${modelCohort.question_version ?? t("未记录")} · ${root?.target_end_date ?? t("目标日未记录")}`}>
      <Sample label={t("独立预测样本")} value={`${t("标签")} ${modelCohort.sample.labelled_root_count} · ${t("评分")} ${modelCohort.sample.scored_root_count} / ${modelCohort.sample.root_denominator}`}
        note={locale === "en-US" ? `${cohortStatusText(modelCohort.status).trim()}; ${t("按服务方、模型、问题版本和时间模式分组，每项独立预测只计一个代表版本。")}` : `${cohortStatusText(modelCohort.status)}；${t("按服务方、模型、问题版本和时间模式分组，每项独立预测只计一个代表版本。")}`} />
      {evaluation?.status === "succeeded" && <Sample label={t("真实标签")} value={labelText(evaluation.actual_label)}
        note={`${evaluation.actual_target_close === null ? t("目标收盘价未记录") : `${t("目标收盘")} ${evaluation.actual_target_close}`}${evaluation.label_available_at ? ` · ${day(evaluation.label_available_at)} ${t("可用")}` : ""} · ${t(copy.evalScoreLabel)} ${scoreParts.length ? scoreParts.join(" · ") : t("无可用数值评分")}`} />}
      {representsSelected && representative?.naive_baseline && <Note>{t("同题基准")} {BASELINE_NAME}：Brier {scoreText(representative.naive_baseline.brier_score)} · Log loss {scoreText(representative.naive_baseline.log_loss)}</Note>}
      {!representsSelected && <Note>{t("每项独立预测只按最高版本号统计；当前选中的旧版本没有单独计入这组分数。")}</Note>}
      {representative && <Note>{t("代表版本：")} {t("第")} {representative.version_no} {t("版")} · {t("分组")} {modelCohort.provider} / {modelCohort.actual_model} / {modelCohort.question_version ?? "—"} · {t("选择规则：")} {evaluations.data.model_cohort_selection_rule ?? t("每项独立预测按最高版本号选一个代表版本")}</Note>}
    </Block>;
  }
  const match = evaluationRootFor(evaluations.data, selectedRootId);
  if (!match) return <Block label={t("到期评估")} title={t("所选预测尚无评估记录")} sub={t("评估区只读已持久化结果；页面不会拉行情或触发计算。")} />;
  const { cohort, root } = match;
  const selected = root.versions.find(version => version.id === selectedVersionId) ?? [...root.versions].sort((left, right) => right.version_no - left.version_no)[0];
  if (!selected) return null;
  const evaluation = selected.latest_evaluation;
  const state = evaluationStateText(evaluation?.status, root.target_end_date);
  const scoreParts = scoresOf(evaluation, t);
  const numericScoring = (selected.model_status === "experimental_joint" || selected.model_status === "baseline_only") && scoreParts.length > 0;
  return <Block aria={t("所选预测的到期评估")} label={t("到期评估 · 所选预测")} title={state} sub={`${t("目标日")} ${root.target_end_date ?? t("未记录")} · ${t("第")} ${selected.version_no} ${t("版")} · ${t(selected.time_mode === "observed" ? "前向观察" : selected.time_mode === "historical_research" ? "历史研究" : "时间模式未知")}`}>
    <Sample label={t("预测样本")} value={`${t("标签")} ${cohort.sample.labelled_root_count} · ${t("评分")} ${cohort.sample.scored_root_count} / ${cohort.sample.root_denominator}`}
      note={locale === "en-US" ? `${cohortStatusText(cohort.status).trim()}; ${t("真实标签与可评分预测分开统计，修订版本不重复计入预测样本。")}` : `${cohortStatusText(cohort.status)}；${t("真实标签与可评分预测分开统计，修订版本不重复计入预测样本。")}`} />
    {evaluation?.status === "succeeded" && <Sample label={t("真实标签")} value={labelText(evaluation.actual_label)}
      note={`${evaluation.actual_target_close === null ? t("目标收盘价未记录") : `${t("目标收盘")} ${evaluation.actual_target_close}`}${evaluation.label_available_at ? ` · ${day(evaluation.label_available_at)} ${t("可用")}` : ""} · ${numericScoring ? `${t(selected.model_status === "baseline_only" ? "行情基线模型评分：" : "联合研究模型评分：")}${scoreParts.join(" · ")}` : t(selected.model_status === "research_only" ? "已到期并记录真实标签，但该版本没有数值概率可评分。" : "真实标签已记录，但当前没有可显示的数值评分。")}`} />}
    {evaluation && evaluation.status !== "succeeded" && <Note>{t(evaluation.status === "blocked_price" ? "目标价格尚不可用，保持待评估。" : evaluation.status === "failed" ? "最近一次评估失败，未生成替代分数。" : "评估记录已创建，等待目标标签成熟。")}</Note>}
  </Block>;
}

type Evaluation = { status: string; brier_score: number | null; log_loss: number | null; direction_correct: boolean | null } | null | undefined;
function scoresOf(evaluation: Evaluation, t: (text: string) => string) {
  if (evaluation?.status !== "succeeded") return [];
  return [
    evaluation.brier_score !== null ? `Brier ${scoreText(evaluation.brier_score)}` : null,
    evaluation.log_loss !== null ? `Log loss ${scoreText(evaluation.log_loss)}` : null,
    evaluation.direction_correct !== null ? `${t("方向")}${t(evaluation.direction_correct ? "正确" : "错误")}` : null,
  ].filter((part): part is string => part !== null);
}

function evaluationRootFor(response: V2EvaluationResponse, rootId: string): { cohort: V2EvaluationCohort; root: V2EvaluationRoot } | null {
  for (const cohort of Object.values(response.cohorts)) {
    const root = cohort.roots.find(item => item.root_id === rootId);
    if (root) return { cohort, root };
  }
  return null;
}

function modelEvaluationCohort(response: V2EvaluationResponse, version: V2VersionDetail): V2ModelEvaluationCohort | null {
  const timeMode = declaredTimeMode(version);
  const provider = asRecord(version.model_manifest.decision_provider);
  const providerName = provider.provider;
  const actualModel = provider.actual_model;
  const questionVersion = provider.question_version;
  if (!timeMode || typeof providerName !== "string" || typeof actualModel !== "string" || typeof questionVersion !== "string") return null;
  return response.model_cohorts?.find(cohort => cohort.time_mode === timeMode
    && cohort.model_status === version.model_status
    && cohort.provider === providerName
    && cohort.actual_model === actualModel
    && cohort.question_version === questionVersion
    && !cohort.control) ?? null;
}

function declaredTimeMode(version: V2VersionDetail): V2ModelEvaluationCohort["time_mode"] {
  for (const metadata of [version.research_report, version.model_manifest]) {
    const value = asRecord(metadata).time_mode;
    if (value === "observed" || value === "historical_research" || value === "unknown") return value;
  }
  return "unknown";
}

function evaluationStateText(status: "pending" | "succeeded" | "blocked_price" | "failed" | undefined, targetEndDate: string | null) {
  if (status === "succeeded") return translatePhrase("评估已记录");
  if (status === "blocked_price") return translatePhrase("等待目标价格");
  if (status === "failed") return translatePhrase("评估失败");
  if (targetEndDate && targetEndDate > new Date().toISOString().slice(0, 10)) return translatePhrase("目标未到期 · 待评估");
  return translatePhrase("待评估");
}

function cohortStatusText(status: V2EvaluationCohort["status"]) {
  if (status === "available") return translatePhrase("样本达到最低门槛");
  if (status === "insufficient_samples") return translatePhrase("样本不足");
  return translatePhrase("尚无可评分预测");
}

function labelText(label: "bearish" | "neutral" | "bullish" | null) {
  if (label === "bearish") return translatePhrase("下跌");
  if (label === "neutral") return translatePhrase("持平");
  if (label === "bullish") return translatePhrase("上涨");
  return translatePhrase("未记录");
}

function scoreText(value: number | null) {
  return value === null ? "—" : value.toFixed(4);
}
