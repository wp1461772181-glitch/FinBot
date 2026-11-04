import { Tx, useLocale } from "./i18n";
import { useEffect, useMemo, useState } from "react";
import type { PriceCandle, PriceHistory, V2VersionDetail } from "./types";
import { CandlestickChart } from "./CandlestickChart";
import { formatTime } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";

export function ForecastPriceContextChart({ symbol, history, detail, showHistoricalOnly }: { symbol: string; history?: PriceHistory | null; detail: ResourceState<{ current: V2VersionDetail; parent: V2VersionDetail | null }> | null; showHistoricalOnly: boolean }) {
  const { locale, t } = useLocale();
  const current = detail?.kind === "ready" ? detail.data.current : null;
  const cutoffDate = current?.market_cutoff_at.slice(0, 10);
  const fixedTargetDate = current ? targetDate(current) : null;
  const candles = useMemo(() => {
    const all = (history?.candles ?? []).filter(isUsablePriceCandle).sort((left, right) => left.trading_date.localeCompare(right.trading_date));
    const anchorIndexes = [cutoffDate, fixedTargetDate].map((date) => date ? all.findIndex((candle) => candle.trading_date === date) : -1).filter((index) => index >= 0);
    if (!anchorIndexes.length) return all.slice(-100);
    const start = Math.max(0, Math.min(...anchorIndexes) - 18);
    const end = Math.min(all.length, Math.max(...anchorIndexes) + 34);
    return all.slice(start, Math.min(end, start + 100));
  }, [history, cutoffDate, fixedTargetDate]);
  const [activeDate, setActiveDate] = useState<string | null>(candles.at(-1)?.trading_date ?? null);
  useEffect(() => setActiveDate(candles.at(-1)?.trading_date ?? null), [symbol, candles]);
  if (!current && !showHistoricalOnly) return null;
  if (!current && !candles.length) return <section className="price-panel price-panel-empty"><div><span className="section-label">{<Tx text={"历史行情"} />}</span><h2>{<Tx text={"暂时没有可展示的历史行情"} />}</h2></div><p>{<Tx text={"本地没有可绘制的 K 线。"} />}</p></section>;
  if (!current) {
    const active = candles.find((candle) => candle.trading_date === activeDate) ?? candles.at(-1)!;
    return <section className="price-panel" aria-label={`${symbol} 历史行情`}>
      <div className="price-panel-heading"><div><span className="section-label">{<Tx text={"历史行情"} />}</span><h2>{symbol} · {t("已保存日线")}</h2></div><span className="tag">{history?.source ?? t("本地行情")}</span></div>
      <p className="price-intro">{<Tx text={"此处仅展示本地保存的历史行情，不包含预测概率、目标日或版本时间标记。"} />}</p>
      <CandlestickChart candles={candles} symbol={symbol} activeDate={active.trading_date} onInspect={setActiveDate} />
      <div className="candle-detail" aria-live="polite"><strong>{active.trading_date}</strong><span>{t("开盘")} {formatPrice(active.open)} · {t("最高")} {formatPrice(active.high)} · {t("最低")} {formatPrice(active.low)} · {t("收盘")} {formatPrice(active.close)}</span>{active.benchmark_close !== null && active.benchmark_close !== undefined && <span>SPY {t("收盘")} {formatPrice(active.benchmark_close)}</span>}</div>
    </section>;
  }
  if (!candles.length) return <section className="price-panel price-panel-empty" aria-label={t("预测行情定位")}><div><span className="section-label">{<Tx text={"固定目标行情"} />}</span><h2>{<Tx text={"暂时没有已保存的 K 线"} />}</h2></div><p>{<Tx text={"预测版本的决策时点与目标日已保存，但本地没有可绘制的 OHLC 行情。"} />}</p><p>{t("行情截止")} {formatTime(current.market_cutoff_at)} · {t("固定目标日")} {targetDate(current) ?? t("未记录")}</p></section>;
  const active = candles.find((candle) => candle.trading_date === activeDate) ?? candles.at(-1)!;
  return <section className="price-panel v3-price-context" aria-label={t("所选预测的固定目标和行情时间边界")}>
    <div className="price-panel-heading"><div><span className="section-label">{<Tx text={"所选预测行情"} />}</span><h2>{symbol} · {t("固定目标与决策行情截止")}</h2></div><span className="tag">{history?.source ?? t("已存行情")}</span></div>
    <p className="price-intro">{<Tx text={"图表只显示本地保存的 K 线。橙线标记该版本固定目标日，实线标记行情截止日；不会把新版判断伪装成历史概率或蜡烛。"} />}</p>
    <CandlestickChart candles={candles} symbol={symbol} cutoffDate={cutoffDate} targetEndDate={fixedTargetDate ?? undefined} activeDate={active.trading_date} onInspect={setActiveDate} />
    <div className="candle-detail" aria-live="polite"><strong>{active.trading_date}</strong><span>{t("开盘")} {formatPrice(active.open)} · {t("最高")} {formatPrice(active.high)} · {t("最低")} {formatPrice(active.low)} · {t("收盘")} {formatPrice(active.close)}</span>{active.benchmark_close !== null && active.benchmark_close !== undefined && <span>SPY {t("收盘")} {formatPrice(active.benchmark_close)}</span>}</div>
    <p className="fine-print price-fine-print">{locale === "en-US" ? `${t("决策时点")} ${formatTime(current.decision_at)} · ${t("行情截止")} ${formatTime(current.market_cutoff_at)} · ${t("固定目标日")} ${fixedTargetDate ?? t("未记录")}. ${t("图表仅定位合同时间边界，不计算未来收益或预测准确率。")}` : `${t("决策时点")} ${formatTime(current.decision_at)} · ${t("行情截止")} ${formatTime(current.market_cutoff_at)} · ${t("固定目标日")} ${fixedTargetDate ?? t("未记录")}。${t("图表仅定位合同时间边界，不计算未来收益或预测准确率。")}`}</p>
  </section>;
}

export function targetDate(version: V2VersionDetail): string | null {
  const value = version.target_contract.target_end_date;
  return typeof value === "string" ? value : null;
}

function isUsablePriceCandle(candle: PriceCandle) {
  return Boolean(candle.trading_date) && [candle.open, candle.high, candle.low, candle.close].every((value) => Number.isFinite(value) && value > 0)
    && candle.high >= Math.max(candle.open, candle.close) && candle.low <= Math.min(candle.open, candle.close);
}

function formatPrice(value: number) { return `$${value.toFixed(2)}`; }
