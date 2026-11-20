// The four cards that follow the stock the pane is on (or the one the card is pinned to): 行情, 研究预测, 最近资料, 官方申报.  Facts only: prices, dates, counts and titles; no buy / sell wording.
import { Sparkline } from "@/components/Sparkline";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { Change } from "@/components/StatTile";
import { getFilingInventory } from "../../../api/market-data";
import { getMaterialLibrary } from "../../../api/material-library";
import { getV2Forecasts } from "../../../api/forecast-v2";
import { getV2Prices } from "../../../api/prices";
import { modelStatusText } from "../../../ForecastShared";
import { NOT_RECORDED } from "../../../forecast-model.mjs";
import { useLocale } from "../../../i18n";
import { appHref } from "../../../legacy-routes.mjs";
import { materialHref } from "../../../material-focus.mjs";
import { hashHref, paths } from "../../../routes.mjs";
import type { V2ModelStatus } from "../../../types";
import { forecastCardModel, priceSummary } from "../../../workspace-cards.mjs";
import { Body, LIST, MoreLink, ROW, ROW_LINK, day } from "./parts";
import { useLoad } from "./use-load";

const MUTED = "text-caption text-muted-foreground";

export function PriceCard({ symbol, wide }: { symbol: string; wide: boolean }) {
  const { t } = useLocale();
  const [state] = useLoad(`price:${symbol}`, signal => getV2Prices(symbol, signal), true);
  return <Body state={state} empty={v => !v.price_history.candles.length}>{v => {
    const candles = v.price_history.candles, s = priceSummary(candles);
    if (!s) return <p className={MUTED}>{t("暂无")}</p>;
    const dir = s.change === null || s.change === 0 ? "flat" : s.change > 0 ? "up" : "down";
    const sign = s.change && s.change > 0 ? "+" : "";
    return <div className="grid gap-1.5">
      <p className="m-0 flex flex-wrap items-baseline gap-2">
        <strong data-num className="font-mono text-title-m font-semibold tabular-nums text-ink">{s.close.toFixed(2)}</strong>
        {s.change !== null && <Change direction={dir} text={`${sign}${s.change.toFixed(2)} (${sign}${(s.pct ?? 0).toFixed(2)}%)`} className="text-small" />}
      </p>
      <Sparkline closes={candles.slice(-63).map(c => c.close)} width={wide ? 520 : 260} height={wide ? 120 : 48} className={wide ? "h-30" : "h-12"} />
      <small className={MUTED}>{t("收盘")} {s.date} · {t("近 3 个月")}</small>
    </div>;
  }}</Body>;
}

// One list call for this card's stock (the workspace read has no deciding model, target date or rootId in the row shape the home page uses).  The card links to that forecast's own page.
export function ForecastCard({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  const [state] = useLoad(`forecast:${symbol}`, signal => getV2Forecasts({ symbols: [symbol], state: "all", limit: 20 }, signal)
    .then(list => forecastCardModel(list.forecasts, symbol)));
  return <div className="grid gap-1.5">
    <Body state={state} empty={v => v === null}>{v => v && <>
      <p className="m-0 text-small"><strong>{t("决策模型")}</strong> {v.model ?? t(NOT_RECORDED)} · {t("目标日")} {v.targetDate ?? t(NOT_RECORDED)}</p>
      {v.probabilities ? <ProbabilityBar probabilities={v.probabilities} /> : <p className={MUTED}>{modelStatusText(v.modelStatus as V2ModelStatus)}</p>}
      <small className={MUTED}>{t("最新版本")} v{v.versionNo} · {t("决策日")} {day(v.decisionAt)}</small>
      <MoreLink href={appHref(v.hash)}>{t("打开这份预测")}</MoreLink></>}</Body>
    <small className={MUTED}>{t("模型意见，未经校准，仅供参考。")}</small>
  </div>;
}

export function MaterialsCard({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  const [state] = useLoad(`materials:${symbol}`, signal => getMaterialLibrary(symbol, { order: "recent", limit: 5, signal }));
  const fresh = (value: string | null) => Boolean(value && Date.now() - new Date(value).valueOf() < 24 * 3600 * 1000);
  return <div className="grid gap-1.5">
    <Body state={state} empty={v => !v.items.length}>{v => <ul className={LIST}>{v.items.map(item =>
      <li key={`${item.source_type}:${item.source_id}`} className={ROW}><a href={appHref(materialHref(symbol, item))} className={ROW_LINK}>{item.title}</a>
        {fresh(item.observed_at) && <span className="rounded-full bg-action-soft px-1.5 text-caption text-action">{t("新")}</span>}<small className={MUTED}>{day(item.published_at)}</small></li>)}</ul>}</Body>
    <MoreLink href={hashHref(paths.materials({ symbol }))}>{t("打开资料库")}</MoreLink>
  </div>;
}

export function FilingsCard({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  const [state] = useLoad(`filings:${symbol}`, signal => getFilingInventory(symbol, signal), true);
  return <div className="grid gap-1.5">
    <Body state={state} empty={v => !v.filings.length}>{v => <ul className={LIST}>{[...v.filings].sort((a, b) => b.filed_at.localeCompare(a.filed_at)).slice(0, 5).map(f =>
      <li key={f.accession_number} className={ROW}><a href={f.source_url} target="_blank" rel="noreferrer" className={ROW_LINK}>{f.form}</a><small className={MUTED}>{day(f.filed_at)}</small></li>)}</ul>}</Body>
    <MoreLink href={hashHref(paths.materials({ symbol }))}>{t("去资料库扫描新申报")}</MoreLink>
  </div>;
}
