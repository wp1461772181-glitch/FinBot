import { Tx, translatePhrase, useLocale } from "./i18n";
import type { V2EvaluationCohort, V2EvaluationResponse, V2EvaluationRoot, V2ModelEvaluationCohort, V2VersionDetail } from "./types";
import { BASELINE_NAME, forecastCopy, hasDecisionProbabilities } from "./forecast-model.mjs";
import { asRecord, asText, formatTime } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";

export function EvaluationReadout({ evaluations, selectedRootId, selectedVersionId, selectedVersionDetail }: { evaluations: ResourceState<V2EvaluationResponse>; selectedRootId: string; selectedVersionId: string; selectedVersionDetail: V2VersionDetail | null }) {
  const { locale, t } = useLocale();
  if (evaluations.kind === "loading") return <section className="v2-evaluation"><p>{<Tx text={"正在读取所选预测的到期评估…"} />}</p></section>;
  if (evaluations.kind === "error") return <section className="v2-evaluation"><p className="v2-notice error" role="alert">{evaluations.message}</p></section>;
  if (selectedVersionDetail && hasDecisionProbabilities(selectedVersionDetail.model_status)) {
    const modelCohort = modelEvaluationCohort(evaluations.data, selectedVersionDetail);
    const decisionProvider = asRecord(selectedVersionDetail.model_manifest.decision_provider);
    const copy = forecastCopy({ model_status: selectedVersionDetail.model_status, provider: asText(decisionProvider.provider), actual_model: asText(decisionProvider.actual_model) });
    if (!modelCohort) return <section className="v2-evaluation"><p className="section-label">{t(copy.evalLabel)}</p><h3>{t(evaluations.data.model_cohorts ? "尚无匹配的模型分组" : "模型分组评估尚不可用")}</h3><p>{t(evaluations.data.model_cohorts ? copy.evalNoMatchBody : "API 尚未提供按模型隔离的评估分组；为避免混淆样本分母，不使用旧的混合分组代替。")}</p></section>;
    const root = modelCohort.roots.find((item) => item.root_id === selectedRootId);
    const representative = root?.versions[0];
    const representsSelected = representative?.id === selectedVersionId;
    const evaluation = representsSelected ? representative?.latest_evaluation ?? null : null;
    const state = evaluationStateText(evaluation?.status, root?.target_end_date ?? null);
    const scoreParts = evaluation?.status === "succeeded" ? [
      evaluation.brier_score !== null ? `Brier ${scoreText(evaluation.brier_score)}` : null,
      evaluation.log_loss !== null ? `Log loss ${scoreText(evaluation.log_loss)}` : null,
      evaluation.direction_correct !== null ? `${t("方向")}${t(evaluation.direction_correct ? "正确" : "错误")}` : null,
    ].filter((part): part is string => part !== null) : [];
    return <section className="v2-evaluation" aria-label={t(copy.evalAria)}>
      <div><p className="section-label">{t(copy.evalLabel)}</p><h3>{representsSelected ? state : t("显示该独立预测的最新代表版本")}</h3><p>{t("模型")} {modelCohort.actual_model} · {t("问题")} {modelCohort.question_version ?? t("未记录")} · {root?.target_end_date ?? t("目标日未记录")}</p></div>
      <div className="v2-evaluation-sample"><span>{<Tx text={"独立预测样本"} />}</span><strong>{t("标签")} {modelCohort.sample.labelled_root_count} · {t("评分")} {modelCohort.sample.scored_root_count} / {modelCohort.sample.root_denominator}</strong><small>{locale === "en-US" ? `${cohortStatusText(modelCohort.status).trim()}; ${t("按服务方、模型、问题版本和时间模式分组，每项独立预测只计一个代表版本。")}` : `${cohortStatusText(modelCohort.status)}；${t("按服务方、模型、问题版本和时间模式分组，每项独立预测只计一个代表版本。")}`}</small></div>
      {evaluation?.status === "succeeded" && <div className="v2-evaluation-result"><span>{<Tx text={"真实标签"} />}</span><strong>{labelText(evaluation.actual_label)}</strong><small>{evaluation.actual_target_close === null ? t("目标收盘价未记录") : `${t("目标收盘")} ${evaluation.actual_target_close}`}{evaluation.label_available_at ? ` · ${formatTime(evaluation.label_available_at)} ${t("可用")}` : ""}</small><p>{t(copy.evalScoreLabel)} {scoreParts.length ? scoreParts.join(" · ") : t("无可用数值评分")}</p></div>}
      {representsSelected && representative?.naive_baseline && <p className="v2-evaluation-note">{t("同题基准")} {BASELINE_NAME}：Brier {scoreText(representative.naive_baseline.brier_score)} · Log loss {scoreText(representative.naive_baseline.log_loss)}</p>}
      {!representsSelected && <p className="v2-evaluation-note">{<Tx text={"每项独立预测只按最高版本号统计；当前选中的旧版本没有单独计入这组分数。"} />}</p>}
      {representative && <p className="v2-evaluation-note">{t("代表版本：")} {t("第")} {representative.version_no} {t("版")} · {t("分组")} {modelCohort.provider} / {modelCohort.actual_model} / {modelCohort.question_version ?? "—"} · {t("选择规则：")} {evaluations.data.model_cohort_selection_rule ?? t("每项独立预测按最高版本号选一个代表版本")}</p>}
    </section>;
  }
  const match = evaluationRootFor(evaluations.data, selectedRootId);
  if (!match) return <section className="v2-evaluation"><p className="section-label">{<Tx text={"到期评估"} />}</p><h3>{<Tx text={"所选预测尚无评估记录"} />}</h3><p>{<Tx text={"评估区只读已持久化结果；页面不会拉行情或触发计算。"} />}</p></section>;
  const { cohort, root } = match;
  const selectedVersion = root.versions.find((version) => version.id === selectedVersionId)
    ?? [...root.versions].sort((left, right) => right.version_no - left.version_no)[0];
  if (!selectedVersion) return null;
  const evaluation = selectedVersion.latest_evaluation;
  const state = evaluationStateText(evaluation?.status, root.target_end_date);
  const scoreParts = evaluation?.status === "succeeded"
    ? [
      evaluation.brier_score !== null ? `Brier ${scoreText(evaluation.brier_score)}` : null,
      evaluation.log_loss !== null ? `Log loss ${scoreText(evaluation.log_loss)}` : null,
      evaluation.direction_correct !== null ? `${t("方向")}${t(evaluation.direction_correct ? "正确" : "错误")}` : null,
    ].filter((part): part is string => part !== null)
    : [];
  const numericScoring = (selectedVersion.model_status === "experimental_joint" || selectedVersion.model_status === "baseline_only") && scoreParts.length > 0;
  return <section className="v2-evaluation" aria-label={t("所选预测的到期评估")}>
    <div><p className="section-label">{<Tx text={"到期评估 · 所选预测"} />}</p><h3>{state}</h3><p>{t("目标日")} {root.target_end_date ?? t("未记录")} · {t("第")} {selectedVersion.version_no} {t("版")} · {t(selectedVersion.time_mode === "observed" ? "前向观察" : selectedVersion.time_mode === "historical_research" ? "历史研究" : "时间模式未知")}</p></div>
    <div className="v2-evaluation-sample"><span>{<Tx text={"预测样本"} />}</span><strong>{t("标签")} {cohort.sample.labelled_root_count} · {t("评分")} {cohort.sample.scored_root_count} / {cohort.sample.root_denominator}</strong><small>{locale === "en-US" ? `${cohortStatusText(cohort.status).trim()}; ${t("真实标签与可评分预测分开统计，修订版本不重复计入预测样本。")}` : `${cohortStatusText(cohort.status)}；${t("真实标签与可评分预测分开统计，修订版本不重复计入预测样本。")}`}</small></div>
    {evaluation?.status === "succeeded" && <div className="v2-evaluation-result"><span>{<Tx text={"真实标签"} />}</span><strong>{labelText(evaluation.actual_label)}</strong><small>{evaluation.actual_target_close === null ? t("目标收盘价未记录") : `${t("目标收盘")} ${evaluation.actual_target_close}`}{evaluation.label_available_at ? ` · ${formatTime(evaluation.label_available_at)} ${t("可用")}` : ""}</small>{numericScoring ? <p>{t(selectedVersion.model_status === "baseline_only" ? "行情基线模型评分：" : "联合研究模型评分：")}{scoreParts.join(" · ")}</p> : <p>{t(selectedVersion.model_status === "research_only" ? "已到期并记录真实标签，但该版本没有数值概率可评分。" : "真实标签已记录，但当前没有可显示的数值评分。")}</p>}</div>}
    {evaluation && evaluation.status !== "succeeded" && <p className="v2-evaluation-note">{t(evaluation.status === "blocked_price" ? "目标价格尚不可用，保持待评估。" : evaluation.status === "failed" ? "最近一次评估失败，未生成替代分数。" : "评估记录已创建，等待目标标签成熟。")}</p>}
  </section>;
}

function evaluationRootFor(response: V2EvaluationResponse, rootId: string): { cohort: V2EvaluationCohort; root: V2EvaluationRoot } | null {
  for (const cohort of Object.values(response.cohorts)) {
    const root = cohort.roots.find((item) => item.root_id === rootId);
    if (root) return { cohort, root };
  }
  return null;
}

function modelEvaluationCohort(response: V2EvaluationResponse, version: V2VersionDetail): V2ModelEvaluationCohort | null {
  const timeMode = declaredTimeMode(version);
  const manifest = version.model_manifest;
  const provider = asRecord(manifest.decision_provider);
  const providerName = provider.provider;
  const actualModel = provider.actual_model;
  const questionVersion = provider.question_version;
  if (!timeMode || typeof providerName !== "string" || typeof actualModel !== "string" || typeof questionVersion !== "string") return null;
  return response.model_cohorts?.find((cohort) => cohort.time_mode === timeMode
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
