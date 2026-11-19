import type { ReactNode } from "react";
import { StatTile } from "@/components/StatTile";
import { useLocale } from "../../i18n";
import { formatMoney, warningLabels } from "../../portfolio-items.mjs";
import type { PortfolioSummary } from "../../api/portfolio-ledger";
import { CashTile } from "./CashTile";
import { Pnl } from "./Pnl";

const money = (value: string | null | undefined) => <span data-num>{formatMoney(value)}</span>;
/** The five smaller numbers are one step below the title size, so a figure with a comma or two still fits its tile at 390 and at 1440. */
const small = (node: ReactNode) => <span className="text-title-s">{node}</span>;

/**
 * The key numbers of the account in one row (design 4.9): 总资产 large, 可用资金 (edited in place), then 持仓市值, 浮动盈亏, 今日盈亏 and 已实现盈亏.  The row is a
 * grid, two columns on a phone, so nothing scrolls sideways at 390.  The figures are the server's, shown by portfolio-items.mjs; 今日盈亏 says 仅供参考 when
 * the server says it is for reference only, as the old page did.  The footnote of the area is the date the prices are from, and the server's own warnings.
 */
export function SummaryRow({ data, onSaveCash }: { data: PortfolioSummary; onSaveCash: (value: string) => Promise<unknown> }) {
  const { t } = useLocale();
  const tile = "gap-1.5 p-3 max-sm:p-3.5";
  const big = (node: ReactNode) => <span className="text-display">{node}</span>;
  const warnings = warningLabels(data.warnings);
  return <section aria-label={t("账户汇总")} data-testid="portfolio-summary" className="flex flex-col gap-2">
    <div className="grid grid-cols-2 gap-2 xl:grid-cols-[minmax(0,1.5fr)_repeat(5,minmax(0,1fr))] xl:gap-3">
      <StatTile className={`${tile} col-span-2 xl:col-span-1`} label={t("总资产")} value={big(data.total_assets === null ? <span data-num>—</span> : money(data.total_assets))} />
      <StatTile className={`${tile} col-span-2 xl:col-span-1`} label={t("可用资金")} value={small(<CashTile funds={data.available_funds} onSave={onSaveCash} />)} footnote={t("你自己可用于加仓、补仓的钱")} />
      <StatTile className={tile} label={t("持仓市值")} value={small(money(data.positions_value))} />
      <StatTile className={tile} label={t("浮动盈亏")} value={small(<Pnl value={data.floating_pnl} />)} />
      <StatTile className={tile} label={data.today_pnl_reference_only ? `${t("今日盈亏")} · ${t("仅供参考")}` : t("今日盈亏")} value={small(<Pnl value={data.today_pnl} />)} />
      <StatTile className={tile} label={t("已实现盈亏")} value={small(<Pnl value={data.realized_pnl} />)} />
    </div>
    <p data-testid="portfolio-price-date" className="text-caption text-muted-foreground">{data.price_date ? `${t("行情数据日期")} ${data.price_date}` : t("还没有可用的行情数据。")}</p>
    {warnings.map(w => <p key={w} role="status" data-testid="portfolio-warning" className="text-small text-ink-2">{t(w)}</p>)}
  </section>;
}
