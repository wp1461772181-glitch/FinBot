import { Tx, useLocale } from "./i18n";
import type { V2ForecastRoot, V2ForecastRoots, V2VersionDetail } from "./types";
import { forecastCopy, hasDecisionProbabilities } from "./forecast-model.mjs";
import { ProbabilityStrip, asText, formatTime, modelStatusText } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";

export function ForecastSummary({ root, roots, detail }: { root: V2ForecastRoot | null; roots: ResourceState<V2ForecastRoots>; detail: ResourceState<{ current: V2VersionDetail; parent: V2VersionDetail | null }> | null }) {
  const { t } = useLocale();
  if (roots.kind === "loading" || detail?.kind === "loading") return <section className="v2-card"><p>{<Tx text={"正在读取所选预测状态…"} />}</p></section>;
  if (roots.kind === "error") return null;
  if (!root) return <section className="v2-card"><p className="section-label">{<Tx text={"所选预测"} />}</p><h3>{<Tx text={"尚无预测版本"} />}</h3><p>{<Tx text={"可以创建一项新研究；预测成功生成后会出现在这里。"} />}</p></section>;
  const current = detail?.kind === "ready" ? detail.data.current : null;
  if (!current) return <section className="v2-card"><p className="section-label">{<Tx text={"所选预测"} />}</p><h3>{<Tx text={"无法读取所选预测的当前版本"} />}</h3><p>{<Tx text={"可重新选择预测日期或刷新页面；不会用其他预测的版本代替它。"} />}</p></section>;
  const joint = current.model_status === "experimental_joint" ? current.joint_probabilities : null;
  const decision = hasDecisionProbabilities(current.model_status) ? current.decision_probabilities : null;
  const provider = current.model_manifest.decision_provider as Record<string, unknown> | undefined;
  const copy = forecastCopy({ model_status: current.model_status, provider: asText(provider?.provider), actual_model: asText(provider?.actual_model) });
  const thesis = asText(provider?.reasoning);
  return <section className="v2-card">
    <p className="section-label">{t("所选预测")} · {t("第")} {current.version_no} {t("版")}</p>
    <h3>{modelStatusText(current.model_status)}</h3>
    <dl><div><dt>{<Tx text={"固定目标日"} />}</dt><dd>{root.target_end_date}</dd></div><div><dt>{<Tx text={"决策时点"} />}</dt><dd>{formatTime(current.decision_at)}</dd></div><div><dt>{<Tx text={"行情截止"} />}</dt><dd>{formatTime(current.market_cutoff_at)}</dd></div></dl>
    {decision ? <><ProbabilityStrip probabilities={decision} label={t(copy.stripLabel)} />
      <p className="v2-limit v2-target-definition">{<Tx text={"上涨：目标日收盘比锚点收盘高 2% 以上。下跌：低 2% 以上。持平：在 ±2% 以内（含边界）。"} />}</p>
      {thesis && <div className="v2-model-view"><span>{<Tx text={"模型的看法"} />}</span><p>{thesis}</p></div>}
      <p className="v2-limit">{copy.summaryNoteBefore ? <>{t(copy.summaryNoteBefore)} {copy.model} {t(copy.summaryNoteAfter)}</> : t(copy.summaryNoteAfter)}</p></>
      : joint ? <ProbabilityStrip probabilities={joint} label={t("实验性联合概率")} />
      : <p className="v2-limit">{t(copy.noProbabilityNote)}</p>}
  </section>;
}
