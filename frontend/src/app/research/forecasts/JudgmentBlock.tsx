import { OpinionCard } from "@/components/OpinionCard";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import type { V2VersionDetail } from "../../../types";
import { NOT_RECORDED, forecastCopy, hasDecisionProbabilities, recordedModel, versionHeader } from "../../../forecast-model.mjs";
import { asText, formatTime } from "../../../ForecastShared";
import { formatDateTime, useLocale } from "../../../i18n";
import { day } from "./format";

const HIDDEN_ROWS = new Set(["probabilities", "times"]);

function Items({ items }: { items: Array<{ t: string } | { v: string } | { time: string | null }> }) {
  const { t, locale } = useLocale();
  return <>{items.map((item, index) => <span key={index}>{"t" in item ? t(item.t) : "v" in item ? item.v : item.time ? formatDateTime(new Date(item.time), locale, "UTC") : "—"}</span>)}</>;
}

/**
 * 判断卡 (design 4.6): the version's call as the opinion material.  The label says whose it is (「模型意见 · 模型 · v3 · 时间」), the title is 第 N 版 · 决策模型 · 决策时间,
 * the bar is the three probabilities with their numbers (or, for a version without any, what the model status was), then the fixed target and the market
 * cut-off, the model's own reading and how the version was made.  The page's one disclaimer is this card's footnote.  It holds what the old version
 * header and summary held: nothing of them is dropped.
 */
export function JudgmentBlock({ version }: { version: V2VersionDetail }) {
  const { t } = useLocale();
  const { actual_model } = recordedModel(version);
  const provider = (version.model_manifest.decision_provider ?? {}) as Record<string, unknown>;
  const copy = forecastCopy({ model_status: version.model_status, provider: asText(provider.provider), actual_model: asText(provider.actual_model) });
  const decision = hasDecisionProbabilities(version.model_status) ? version.decision_probabilities : null;
  const joint = version.model_status === "experimental_joint" ? version.joint_probabilities : null;
  const probabilities = decision ?? joint;
  const thesis = asText(provider.reasoning);
  const confidence = provider.confidence;
  const rows = versionHeader(version).filter(row => !HIDDEN_ROWS.has(row.id));
  const target = typeof version.target_contract.target_end_date === "string" ? version.target_contract.target_end_date : null;
  return <OpinionCard data-testid="forecast-judgment" model={actual_model} version={`v${version.version_no}`} time={day(version.decision_at)} disclaimer>
    <h2 className="text-title-s text-ink [overflow-wrap:anywhere]">{t("第")} {version.version_no} {t("版")} · <span className="font-mono">{actual_model ?? t(NOT_RECORDED)}</span> · {t("决策时点")} {day(version.decision_at)}</h2>
    {probabilities
      ? <ProbabilityBar probabilities={probabilities} status={version.model_status} />
      : <p className="text-small text-ink-2">{t(copy.noProbabilityNote)}</p>}
    {probabilities && <p className="text-caption text-muted-foreground">{decision ? t(copy.stripLabel) : t("实验性联合概率")}{typeof confidence === "number" ? ` · ${t("分布集中度")} ${Math.round(confidence * 100)}%（${t("不是准确率")}）` : ""}</p>}
    <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 text-small sm:grid-cols-3">
      <div><dt className="text-caption text-muted-foreground">{t("固定目标日")}</dt><dd data-testid="judgment-target-date" className="m-0 font-mono tabular-nums text-ink">{target ?? t("未记录")}</dd></div>
      <div><dt className="text-caption text-muted-foreground">{t("行情截止")}</dt><dd className="m-0 font-mono tabular-nums text-ink">{formatTime(version.market_cutoff_at)}</dd></div>
      <div><dt className="text-caption text-muted-foreground">{t("决策时点")}</dt><dd className="m-0 font-mono tabular-nums text-ink">{formatTime(version.decision_at)}</dd></div>
    </dl>
    {decision && <p className="text-caption text-muted-foreground">{t("上涨：目标日收盘比锚点收盘高 2% 以上。下跌：低 2% 以上。持平：在 ±2% 以内（含边界）。")}</p>}
    {decision && thesis && <div className="flex flex-col gap-1"><p className="text-caption font-medium text-muted-foreground">{t("模型的看法")}</p><p className="text-body text-ink [overflow-wrap:anywhere]">{thesis}</p></div>}
    {decision && <p className="text-caption text-muted-foreground">{copy.summaryNoteBefore ? <>{t(copy.summaryNoteBefore)} {copy.model} {t(copy.summaryNoteAfter)}</> : t(copy.summaryNoteAfter)}</p>}
    <dl data-testid="judgment-meta" className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 border-t border-line pt-3 text-small">
      {rows.map(row => <div key={row.id} className="contents"><dt className="text-caption text-muted-foreground">{t(row.label)}</dt><dd className="m-0 text-ink-2 [overflow-wrap:anywhere]"><Items items={row.items} /></dd></div>)}
    </dl>
  </OpinionCard>;
}
