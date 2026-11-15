import { useEffect, useState } from "react";
import { ApiError } from "./api/base";
import { getV2Evaluations } from "./api/forecast-v2";
import { BASELINE_NAME, scoreCard } from "./forecast-model.mjs";
import { Tx, translatePhrase, useLocale } from "./i18n";
import type { V2EvaluationResponse, V2ModelEvaluationCohort } from "./types";

const RULE_TEXT = "预先约定的规则：一个预测模型累计 30 个已评分的独立预测后，如果它的 Brier 分数差于同题基准 naive-vol-v1，就更换模型或停止显示数字。赢过基准不会改变任何事，概率仍标注未校准。30 个样本只能发现明显失败，分不出接近的模型。换模型后重新计数。";
const BASELINE_EXPLAINER = "naive-vol-v1 只用当时的波动率和距目标日的剩余时间，假设不涨不跌，不读任何材料。";

export function modelStatusLabel(status: string) {
  if (status === "research_only") return translatePhrase("研究结果（未输出概率）");
  if (status === "experimental_jev") return translatePhrase("Jev 实验模型");
  if (status === "experimental_llm") return translatePhrase("推理模型实验预测");
  if (status === "experimental_joint") return translatePhrase("联合研究模型");
  if (status === "baseline_only") return translatePhrase("基线模型");
  return translatePhrase("模型状态未记录");
}

function loadMessage(error: unknown) {
  return translatePhrase(error instanceof ApiError ? error.message : "暂时无法读取到期评估。");
}

/** 模型成绩: every symbol together, because the 30-root rule means nothing per symbol. */
export function ModelScoresPage() {
  const { t } = useLocale();
  const [state, setState] = useState<{ kind: "loading" } | { kind: "ready"; data: V2EvaluationResponse } | { kind: "error"; message: string }>({ kind: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    getV2Evaluations(undefined, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ kind: "ready", data }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setState({ kind: "error", message: loadMessage(error) }); });
    return () => controller.abort();
  }, []);
  return <section className="workspace-stack">
    <section className="workspace-intro"><div><p className="eyebrow">{t("到期评估")}</p><h2>{t("按模型分组查看已到期预测")}</h2><p>{t("每组只统计同一时间模式、模型、服务方和问题版本的代表版本。未到期样本显示为待评，不混入其他模型的指标。")}</p></div></section>
    <p className="fine-print model-score-rule">{t(RULE_TEXT)}</p>
    {state.kind === "loading" && <p className="inventory-status">{<Tx text={"正在读取评估结果…"} />}</p>}
    {state.kind === "error" && <p className="inventory-status inventory-error" role="alert">{state.message}</p>}
    {state.kind === "ready" && (state.data.model_cohorts?.length ? <ModelCohortGroups cohorts={state.data.model_cohorts} minimumScoredRoots={state.data.minimum_scored_roots} /> : <div className="model-cohort-list"><div className="evaluation-empty-state"><h2>{state.data.model_cohorts ? t("还没有模型分组评估") : t("模型分组数据暂不可用")}</h2><p>{<Tx text={"这里不会用旧版离线报告或跨模型混合分组填补。预测到期并获得可用行情后，结果会进入对应模型组。"} />}</p></div></div>)}
  </section>;
}

const fixed = (value: number | null) => (value === null ? "—" : value.toFixed(3));

/** Forecast-model cohorts are scored apart from earlier records (old Jev forecasts, the retired control) and never pooled. */
export function ModelCohortGroups({ cohorts, minimumScoredRoots }: { cohorts: V2ModelEvaluationCohort[]; minimumScoredRoots: number }) {
  const { locale, t } = useLocale();
  const groups = [
    { key: "llm", title: "预测模型", note: "设置中选定的预测模型给出的预测，每个独立预测算一个样本。", items: cohorts.filter((c) => !c.control && c.model_status === "experimental_llm") },
    { key: "earlier", title: "早期版本", note: "更早的记录，包括 Jev 直接给出的旧预测和已停用的对照记录。", items: cohorts.filter((c) => c.control || c.model_status !== "experimental_llm") },
  ].filter((group) => group.items.length);
  return <div className="model-cohort-list">{groups.map((group) => <section key={group.key} className={`model-cohort-group model-cohort-group-${group.key}`}>
    <h2 className="model-cohort-group-title">{t(group.title)}</h2><p className="fine-print">{t(group.note)}</p>
    {group.items.map((cohort, index) => {
      const versions = cohort.roots.flatMap((root) => root.versions);
      const scored = versions.map((version) => version.latest_evaluation).filter((evaluation) => evaluation?.status === "succeeded");
      const average = (values: Array<number | null | undefined>) => { const valid = values.filter((value): value is number => typeof value === "number"); return valid.length ? (valid.reduce((sum, value) => sum + value, 0) / valid.length).toFixed(3) : "—"; };
      const card = scoreCard(cohort);
      return <article className="model-cohort-card" key={`${cohort.model_status}-${cohort.provider}-${cohort.actual_model}-${cohort.question_version ?? "none"}-${cohort.time_mode}-${index}`}>
        <div className="section-heading"><div><p className="eyebrow">{t(cohort.time_mode === "observed" ? "真实观察" : cohort.time_mode === "historical_research" ? "历史研究" : "时间模式未分类")} · {t(modelStatusLabel(cohort.model_status))}{cohort.control ? ` · ${t("已停用的对照")}` : ""}</p><h2>{cohort.provider} / {cohort.actual_model}</h2></div><span>{t(cohort.status === "available" ? "指标可用" : cohort.status === "pending" ? "等待到期" : "样本不足")}</span></div>
        <p className="fine-print">{t("问题版本")}: {cohort.question_version ?? t("未记录")} · {t("样本按同组最高版本计数")}</p>
        {card.bannerKey && <p className="v2-notice error" role="alert">{t(card.bannerKey)}</p>}
        <div className="overview-metrics"><article><span>{<Tx text={"独立预测样本"} />}</span><strong>{cohort.sample.root_denominator}</strong><small>{<Tx text={"同组代表记录"} />}</small></article><article><span>{<Tx text={"已标注 / 已评分"} />}</span><strong>{cohort.sample.labelled_root_count} / {cohort.sample.scored_root_count}</strong><small>{cohort.sample.unscored_root_count} {t("条尚未评分")}</small></article>{cohort.status === "available"
          ? <><article><span>{<Tx text={"平均 Brier"} />}</span><strong>{average(scored.map((value) => value?.brier_score))}</strong><small>{<Tx text={"仅已成功评分的版本"} />}</small></article><article><span>{<Tx text={"平均 Log loss"} />}</span><strong>{average(scored.map((value) => value?.log_loss))}</strong><small>{<Tx text={"仅已成功评分的版本"} />}</small></article></>
          : <article><span>{<Tx text={"平均分数"} />}</span><strong>{locale === "en-US" ? `${t("样本不足")} (${cohort.sample.scored_root_count}/${minimumScoredRoots})` : `${t("样本不足")}（${cohort.sample.scored_root_count}/${minimumScoredRoots}）`}</strong><small>{<Tx text={"已评分的独立预测达到下限后才显示平均值"} />}</small></article>}</div>
        {card.showMeans && <>
          <div className="overview-metrics">
            <article><span>{t("模型平均 Brier")}</span><strong>{fixed(card.modelBrier)}</strong><small>{t("同题基准")} {BASELINE_NAME} {fixed(card.baselineBrier)}</small></article>
            <article><span>{t("模型平均 Log loss")}</span><strong>{fixed(card.modelLogLoss)}</strong><small>{t("同题基准")} {BASELINE_NAME} {fixed(card.baselineLogLoss)}</small></article>
            <article><span>{t("可比较的独立预测")}</span><strong>{card.pairedRootCount}</strong><small>{card.baselineUnavailableRootCount > 0 ? `${card.baselineUnavailableRootCount} ${t("条缺少基准输入，未计入比较")}` : t("模型与基准在同一批预测上比较")}</small></article>
          </div>
          <p className="fine-print">{t(BASELINE_EXPLAINER)}</p>
        </>}
      </article>;
    })}
  </section>)}</div>;
}
