import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/state/EmptyState";
import { CandlestickChart } from "../../../CandlestickChart";
import type { PriceCandle, PriceHistory, V2VersionDetail } from "../../../types";
import { useLocale } from "../../../i18n";
import { price } from "./format";

function usable(candle: PriceCandle) {
  return Boolean(candle.trading_date) && [candle.open, candle.high, candle.low, candle.close].every(value => Number.isFinite(value) && value > 0)
    && candle.high >= Math.max(candle.open, candle.close) && candle.low <= Math.min(candle.open, candle.close);
}

/**
 * 行情图 (design 4.6): the saved candles around the version's two dates, with the market cut-off and the fixed target marked on them (the chart's own
 * overlays, in the colour and type tokens).  The window is the old one: 18 sessions before the earlier mark, 34 after the later, at most 100.  The picture
 * only places the contract's dates; it computes no return and no accuracy.
 */
export function PriceContext({ symbol, history, version }: { symbol: string; history: PriceHistory | null | undefined; version: V2VersionDetail }) {
  const { t } = useLocale();
  const cutoffDate = version.market_cutoff_at.slice(0, 10);
  const target = typeof version.target_contract.target_end_date === "string" ? version.target_contract.target_end_date : null;
  const candles = useMemo(() => {
    const all = (history?.candles ?? []).filter(usable).sort((left, right) => left.trading_date.localeCompare(right.trading_date));
    const anchors = [cutoffDate, target].map(date => date ? all.findIndex(candle => candle.trading_date === date) : -1).filter(index => index >= 0);
    if (!anchors.length) return all.slice(-100);
    const start = Math.max(0, Math.min(...anchors) - 18);
    const end = Math.min(all.length, Math.max(...anchors) + 34);
    return all.slice(start, Math.min(end, start + 100));
  }, [history, cutoffDate, target]);
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => setActive(candles.at(-1)?.trading_date ?? null), [symbol, candles]);
  const shown = candles.find(candle => candle.trading_date === active) ?? candles.at(-1) ?? null;
  return <section data-testid="forecast-chart" aria-label={t("所选预测的固定目标和行情时间边界")} className="material-fact flex min-w-0 flex-col gap-2 p-4">
    <div className="flex flex-wrap items-baseline gap-x-3">
      <h2 className="text-title-s text-ink mb-3">{t("行情")}</h2>
      <p className="font-mono text-caption text-muted-foreground mb-3">{symbol} · {t("固定目标与决策行情截止")}</p>
    </div>
    {!shown
      ? <EmptyState title={t("暂时没有已保存的 K 线")} description={t("预测版本的决策时点与目标日已保存，但本地没有可绘制的 OHLC 行情。")} className="py-6" />
      : <>
        <p className="text-small text-muted-foreground">{t("图表只显示本地保存的 K 线。强调色的线标记该版本的固定目标日，另一条线标记行情截止日；不会把新版判断伪装成历史概率或蜡烛。")}</p>
        <CandlestickChart candles={candles} symbol={symbol} activeDate={shown.trading_date} onInspect={setActive} cutoffDate={cutoffDate} targetEndDate={target ?? undefined} />
        <p data-testid="candle-readout" aria-live="polite" className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-caption tabular-nums text-muted-foreground">
          <span className="text-ink">{shown.trading_date}</span>
          <span>{t("开盘")} {price(shown.open)}</span><span>{t("最高")} {price(shown.high)}</span><span>{t("最低")} {price(shown.low)}</span><span>{t("收盘")} {price(shown.close)}</span>
          {shown.benchmark_close !== null && shown.benchmark_close !== undefined && <span>SPY {t("收盘")} {price(shown.benchmark_close)}</span>}
        </p>
        <p className="text-caption text-muted-foreground">{t("图表仅定位合同时间边界，不计算未来收益或预测准确率。")}</p>
      </>}
  </section>;
}
