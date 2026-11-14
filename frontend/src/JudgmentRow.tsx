import { useLocale } from "./i18n";
import { appHref } from "./legacy-routes.mjs";
import { NOT_RECORDED } from "./forecast-model.mjs";
import type { JudgmentRowModel } from "./forecast-home.mjs";
import { Parts, formatTime } from "./ForecastShared";

/**
 * One earnings judgment on the home page: 偏涨 or 偏跌, 把握, when, which model, and the result once the first
 * session has closed.  It takes no probabilities and cannot render a probability strip (design §2 rule 1 and 2).
 */
export function JudgmentRow({ model, mark, withForecastNote }: { model: JudgmentRowModel; mark: string | null; withForecastNote: boolean }) {
  const { t } = useLocale();
  return <li className="forecast-row judgment-row">
    <a className="forecast-row-link" href={appHref(model.hash)}>
      <span className="forecast-row-head">
        <strong>{model.symbol}</strong>
        {mark && <span className="tag">{t(mark)}</span>}
        <span className="forecast-row-type">{t(model.typeLabel)}</span>
      </span>
      <span className="forecast-row-body">
        <span className="judgment-direction">{t(model.direction)}{model.confidence ? ` · ${t(model.confidence)}` : ""}</span>
        <span>{formatTime(model.time)}</span>
        <span>{t("决策模型")} {model.model ?? t(NOT_RECORDED)}{model.modelFirstStage ? ` (${t("首条消息时的模型")})` : ""}</span>
        <span>{t(model.result)}</span>
        {model.afterHours && <span><Parts parts={model.afterHours.parts} /></span>}
      </span>
    </a>
    {withForecastNote && <small className="forecast-row-note">{t("两者问题不同：财报判断看首个交易日，正式预测看 20 个交易日。")}</small>}
  </li>;
}
