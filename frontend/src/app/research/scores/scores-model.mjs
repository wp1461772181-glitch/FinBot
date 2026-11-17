import { BASELINE_NAME, scoreCard } from "../../../forecast-model.mjs";

// The model scores page's pure rules (P6.4).  The cohort grouping, the floor and the baseline comparison are the old page's and `forecast-model.mjs`'s `scoreCard`
// (untouched); this file holds what the old page computed inline (the averages, the two groups) so the page and its check read the same function.

export const RULE_TEXT = "预先约定的规则：一个预测模型累计 30 个已评分的独立预测后，如果它的 Brier 分数差于同题基准 naive-vol-v1，就更换模型或停止显示数字。赢过基准不会改变任何事，概率仍标注未校准。30 个样本只能发现明显失败，分不出接近的模型。换模型后重新计数。";
export const BASELINE_EXPLAINER = "naive-vol-v1 只用当时的波动率和距目标日的剩余时间，假设不涨不跌，不读任何材料。";
export { BASELINE_NAME };

/** The words for a cohort's model status (a zh-CN phrase key). */
export function modelStatusPhrase(status) {
  if (status === "research_only") return "研究结果（未输出概率）";
  if (status === "experimental_jev") return "Jev 实验模型";
  if (status === "experimental_llm") return "推理模型实验预测";
  if (status === "experimental_joint") return "联合研究模型";
  if (status === "baseline_only") return "基线模型";
  return "模型状态未记录";
}

/** The time-mode words of a cohort's eyebrow. */
export const timeModePhrase = (mode) => (mode === "observed" ? "真实观察" : mode === "historical_research" ? "历史研究" : "时间模式未分类");
/** The words of a cohort's status chip. */
export const cohortStatusPhrase = (status) => (status === "available" ? "指标可用" : status === "pending" ? "等待到期" : "样本不足");

/** The two groups of the page: the forecast model's own cohorts, and the earlier records (old Jev forecasts, the retired control); a group with no cohort is left out. */
export function cohortGroups(cohorts) {
  return [
    { key: "llm", title: "预测模型", note: "设置中选定的预测模型给出的预测，每个独立预测算一个样本。", items: cohorts.filter((c) => !c.control && c.model_status === "experimental_llm") },
    { key: "earlier", title: "早期版本", note: "更早的记录，包括 Jev 直接给出的旧预测和已停用的对照记录。", items: cohorts.filter((c) => c.control || c.model_status !== "experimental_llm") },
  ].filter((group) => group.items.length);
}

/** The mean of the numbers among `values` (a missing or non-number value is left out); null when none is left. */
export function mean(values) {
  const valid = values.filter((value) => typeof value === "number");
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
}

/** The cohort's own average Brier and Log loss: over the versions whose latest evaluation succeeded (the old page's rule). */
export function cohortAverages(cohort) {
  const scored = (cohort.roots ?? []).flatMap((root) => root.versions).map((version) => version.latest_evaluation).filter((evaluation) => evaluation?.status === "succeeded");
  return { brier: mean(scored.map((value) => value?.brier_score)), logLoss: mean(scored.map((value) => value?.log_loss)) };
}

/** A score to three places, as the old page wrote it; null stays null (the caller says what to show instead). */
export const fixed3 = (value) => (typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : null);

/**
 * What a cohort card shows.  Below the floor (anything but `available`) there is NO number for the averages and none for the baseline comparison: the card says
 * 样本不足 and the floor.  The floor comes from the server (`minimum_scored_roots`); the verdict is the cohort's `status`.
 */
export function cohortView(cohort, minimumScoredRoots) {
  const available = cohort.status === "available";
  const card = scoreCard(cohort);
  const averages = available ? cohortAverages(cohort) : { brier: null, logLoss: null };
  return {
    available,
    sample: cohort.sample,
    floor: minimumScoredRoots,
    brier: fixed3(averages.brier),
    logLoss: fixed3(averages.logLoss),
    banner: card.bannerKey,
    comparison: card.showMeans ? {
      pairedRootCount: card.pairedRootCount,
      baselineUnavailableRootCount: card.baselineUnavailableRootCount,
      brier: { model: card.modelBrier, baseline: card.baselineBrier, bars: compareBars(card.modelBrier, card.baselineBrier) },
      logLoss: { model: card.modelLogLoss, baseline: card.baselineLogLoss, bars: compareBars(card.modelLogLoss, card.baselineLogLoss) },
    } : null,
  };
}

/** The widths (percent of the longer of the two) of a model-versus-baseline pair of bars: both start at zero, so the lengths are the numbers' real ratio. */
export function compareBars(model, baseline) {
  if (typeof model !== "number" || typeof baseline !== "number") return null;
  const top = Math.max(model, baseline);
  const width = (value) => (top > 0 ? Math.round((value / top) * 1000) / 10 : 0);
  return { model: width(model), baseline: width(baseline) };
}

/** A stable key for one cohort card. */
export const cohortKey = (cohort, index) => `${cohort.model_status}-${cohort.provider}-${cohort.actual_model}-${cohort.question_version ?? "none"}-${cohort.time_mode}-${index}`;
