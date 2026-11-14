import { useLocale } from "./i18n";
import { appHref } from "./legacy-routes.mjs";
import { NOT_RECORDED } from "./forecast-model.mjs";
import { attentionLabel } from "./forecast-home.mjs";
import type { AttentionTier, FormalRowModel } from "./forecast-home.mjs";
import { Parts, ProbabilityStrip, modelStatusText } from "./ForecastShared";
import type { V2ModelStatus } from "./types";

/**
 * One formal forecast on the home page: three probabilities, a target date, the deciding model and the version.
 * It never takes a judgment, and it has no direction word (design §2 rule 1 and 2).
 */
export function FormalForecastRow({ model, tier, withJudgmentNote }: { model: FormalRowModel; tier: AttentionTier; withJudgmentNote: boolean }) {
  const { t } = useLocale();
  const why = attentionLabel(tier);
  return <li className={`forecast-row formal-row${tier !== 5 ? ` is-tier-${tier}` : ""}`}>
    <a className="forecast-row-link" href={appHref(model.hash)}>
      <span className="forecast-row-head">
        <strong>{model.symbol}</strong>
        {model.mark && <span className="tag">{t(model.mark)}</span>}
        <span className="forecast-row-type"><Parts parts={model.titleParts} /></span>
        {why && <span className="tag is-attention">{t(why)}</span>}
        {model.expired && <span className="tag">{t("已到期")}</span>}
      </span>
      <span className="forecast-row-body">
        {model.probabilities ? <ProbabilityStrip probabilities={model.probabilities} label={t("三类概率")} compact /> : <span>{modelStatusText(model.modelStatus as V2ModelStatus)}</span>}
        <span>{t("目标日")} {model.targetDate ?? t(NOT_RECORDED)}</span>
        <span>{t("决策模型")} {model.model ?? t(NOT_RECORDED)}</span>
      </span>
    </a>
    {withJudgmentNote && <small className="forecast-row-note">{t("两者问题不同：财报判断看首个交易日，正式预测看 20 个交易日。")}</small>}
  </li>;
}
