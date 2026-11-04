import { formatDateTime, useLocale } from "./i18n";
import { versionHeader } from "./forecast-model.mjs";
import type { HeaderVersion } from "./forecast-model.mjs";

function formatTime(value: string | null, locale: "zh-CN" | "en-US") {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(date, locale, "UTC");
}

/** Who made this call, how, on what question and with what status, for one saved version.  Nothing is collapsed. */
export function ForecastVersionHeader({ version }: { version: HeaderVersion }) {
  const { locale, t } = useLocale();
  const rows = versionHeader(version);
  const showsProbabilities = rows.some((row) => row.id === "probabilities");
  return <section className="v2-card v2-version-header" aria-label={t("模型与版本信息")}>
    <p className="section-label">{t("模型与版本信息")}</p>
    <dl>
      {rows.map((row) => <div key={row.id}>
        <dt>{t(row.label)}</dt>
        <dd>{row.items.map((item, index) => <span key={index}>{"t" in item ? t(item.t) : "v" in item ? item.v : formatTime(item.time, locale)}</span>)}</dd>
      </div>)}
    </dl>
    {showsProbabilities && <p className="v2-limit">{t("概率未经校准，属实验性信息。仅供参考，买不买由你决定。")}</p>}
  </section>;
}
