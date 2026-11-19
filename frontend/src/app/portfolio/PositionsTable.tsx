import type { MouseEvent, ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import { useLocale } from "../../i18n";
import { formatMoney, formatPercent, formatPrice, formatShares } from "../../portfolio-items.mjs";
import type { PortfolioPosition } from "../../api/portfolio-ledger";
import { Pnl } from "./Pnl";

/** The eight columns of the table (a desktop); below xl the same cells are a card, two to a line. */
export const COLUMNS = "xl:grid-cols-[minmax(5.5rem,1.1fr)_repeat(4,minmax(4.5rem,1fr))_minmax(6rem,1.2fr)_minmax(4rem,0.8fr)_minmax(7.5rem,1.4fr)]";

/** A label that names a cell on a card (the header row names it on the table). */
const Label = ({ children }: { children: ReactNode }) => <span className="text-caption text-muted-foreground xl:hidden">{children}</span>;

/** One cell: numbers are in the monospace face and, on the table, line up on the right. */
function Cell({ label, children, className }: { label: ReactNode; children: ReactNode; className?: string }) {
  return <div role="cell" className={cn("flex min-w-0 flex-col gap-0.5 xl:items-end xl:text-right", className)}>
    <Label>{label}</Label>
    <span className="font-mono text-small tabular-nums text-ink">{children}</span>
  </div>;
}

export function PositionsHeader() {
  const { t } = useLocale();
  const cell = "text-caption text-muted-foreground xl:text-right";
  return <div role="rowgroup" className="hidden xl:block">
    <div role="row" className={cn("grid items-center gap-x-4 border-b border-line px-3 py-2", COLUMNS)}>
      <span role="columnheader" className="text-caption text-muted-foreground">{t("代码")}</span>
      <span role="columnheader" className={cell}>{t("股数")}</span>
      <span role="columnheader" className={cell}>{t("平均成本")}</span>
      <span role="columnheader" className={cell}>{t("摊薄成本")}</span>
      <span role="columnheader" className={cell}>{t("最新价")}</span>
      <span role="columnheader" className={cell}>{t("市值")}</span>
      <span role="columnheader" className={cell}>{t("仓位占比")}</span>
      <span role="columnheader" className={cell}>{t("浮动盈亏")}</span>
    </div>
  </div>;
}

/**
 * One position: a row of the table on a desktop, a card on a phone, the same cells either way (the grid lays them out), and the same one node when it opens:
 * the panel is a second row of the same group, so widening or narrowing the window never mounts it again.  The whole row opens it for a pointer; the
 * button in the first cell is the way in from the keyboard (Enter or Space, `aria-expanded`).  `unsaved` marks a plan edited and not yet saved.
 */
export function PositionRow({ position, open, unsaved, onToggle, panel }: { position: PortfolioPosition; open: boolean; unsaved: boolean; onToggle: () => void; panel: ReactNode }) {
  const { t } = useLocale();
  const symbol = position.symbol;
  // A press on the row (not on something in it that does its own thing) opens it.
  const press = (event: MouseEvent<HTMLElement>) => { if (!(event.target as HTMLElement).closest("a,button,input,textarea")) onToggle(); };
  return <div role="rowgroup" data-testid="pf-position" data-symbol={symbol} data-open={open || undefined}
    className="flex flex-col rounded-md border border-line bg-surface xl:rounded-none xl:border-0 xl:border-b xl:bg-transparent xl:last:border-b-0">
    <div role="row" onClick={press} className={cn("grid cursor-pointer grid-cols-2 items-start gap-x-3 gap-y-2 p-3 hover:bg-hover max-xl:rounded-md xl:items-center xl:gap-x-4 xl:px-3 xl:py-2.5", COLUMNS)}>
      <div role="cell" className="col-span-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 xl:col-span-1">
        <button type="button" data-testid="pf-toggle" aria-expanded={open} aria-controls={`pf-panel-${symbol}`} onClick={onToggle}
          className="group/toggle -ml-1 inline-flex min-h-8 items-center gap-1 rounded-sm px-1 text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring max-xl:min-h-11">
          <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-aria-expanded/toggle:rotate-90 motion-reduce:transition-none" />
          <span className="font-mono text-body font-semibold">{symbol}</span>
        </button>
        {unsaved && <span data-testid="pf-unsaved"><StatusBadge kind="neutral" className="h-5">{t("未保存")}</StatusBadge></span>}
      </div>
      <Cell label={t("股数")}>{formatShares(position.shares)}</Cell>
      <Cell label={t("平均成本")}>{formatPrice(position.avg_cost)}</Cell>
      <Cell label={t("摊薄成本")}>{formatPrice(position.diluted_cost)}</Cell>
      <Cell label={t("最新价")}>
        {position.price === null ? <span className="font-sans text-muted-foreground">{t("暂无")}</span> : formatPrice(position.price)}
        {position.price_date && <span className="block font-sans text-caption text-muted-foreground">{position.price_date}</span>}
      </Cell>
      <Cell label={t("市值")}>{formatMoney(position.market_value)}</Cell>
      <Cell label={t("仓位占比")}>{formatPercent(position.weight_pct)}</Cell>
      <div role="cell" className="col-span-2 flex min-w-0 flex-col gap-0.5 xl:col-span-1 xl:items-end">
        <Label>{t("浮动盈亏")}</Label>
        <Pnl value={position.floating_pnl} className="text-small" />
        {position.floating_pnl_pct !== null && <Pnl value={position.floating_pnl_pct} percent className="text-caption" />}
      </div>
    </div>
    {open && <div role="row"><div role="cell" id={`pf-panel-${symbol}`} data-testid="pf-panel" className="border-t border-line p-3 xl:px-4 xl:py-4">{panel}</div></div>}
  </div>;
}
