import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useLocale } from "../../i18n";
import type { PortfolioTransaction } from "../../api/portfolio-ledger";
import { ledgerCells } from "./portfolio-view.mjs";

const COLS = "sm:grid-cols-[6.5rem_5rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]";

/**
 * A list of ledger records: date, kind, quantity, price (or amount) and fee, each with its own 删除 (which asks first, and says that the positions and the
 * cash are worked out again from the records that are left).  `symbol` shows the code too, for the list that holds every record.  `anchor` is where the focus
 * goes when a deleted record's own button is gone.
 */
export function RecordList({ records, withSymbol = false, busy, onDelete, anchor, label }: {
  records: PortfolioTransaction[]; withSymbol?: boolean; busy: boolean; onDelete: (tx: PortfolioTransaction, anchor: string) => void; anchor: string; label: string;
}) {
  const { t } = useLocale();
  const cols = withSymbol ? "sm:grid-cols-[6.5rem_4.5rem_5rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]" : COLS;
  const num = "font-mono tabular-nums sm:text-right";
  return <div role="table" aria-label={label} data-testid="record-list" className="flex flex-col">
    <div role="rowgroup" className="hidden sm:block">
      <div role="row" className={cn("grid items-center gap-x-3 border-b border-line pb-1.5 text-caption text-muted-foreground", cols)}>
        <span role="columnheader">{t("日期")}</span>
        {withSymbol && <span role="columnheader">{t("代码")}</span>}
        <span role="columnheader">{t("类型")}</span>
        <span role="columnheader" className="text-right">{t("数量")}</span>
        <span role="columnheader" className="text-right">{t("价格 / 金额")}</span>
        <span role="columnheader" className="text-right">{t("手续费")}</span>
        <span role="columnheader" className="w-8"><span className="sr-only">{t("操作")}</span></span>
      </div>
    </div>
    <div role="rowgroup" className="flex flex-col">
      {records.map(tx => {
        const cells = ledgerCells(tx);
        return <div role="row" key={tx.id} data-testid="record-row" data-id={tx.id} className={cn("relative flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-line py-2 pr-12 text-small last:border-b-0 sm:grid sm:items-center sm:pr-0", cols)}>
          <span role="cell" className="font-mono tabular-nums text-ink-2">{tx.occurred_on}</span>
          {withSymbol && <span role="cell" className="font-mono font-semibold text-ink">{tx.symbol || "—"}</span>}
          <span role="cell" className="text-ink">{t(cells.label)}</span>
          <span role="cell" className={cn(num, "text-ink")}>{cells.quantity}</span>
          <span role="cell" className={cn(num, "text-ink")}>{cells.price}</span>
          <span role="cell" className={cn(num, "text-ink-2")}>{cells.fee ? <><span className="font-sans text-caption text-muted-foreground sm:hidden">{t("手续费")} </span>{cells.fee}</> : null}</span>
          <span role="cell" className="absolute top-1 right-0 flex items-center sm:static">
            <Button type="button" variant="ghost" size="icon-sm" disabled={busy} data-testid="record-delete" className="max-sm:size-10" aria-label={`${t("删除")} ${tx.occurred_on} ${tx.symbol} ${t(cells.label)}`.replace(/\s+/g, " ")}
              onClick={() => onDelete(tx, anchor)}><Trash2 aria-hidden="true" /></Button>
          </span>
          {tx.note && <span role="cell" data-testid="ledger-note" className="w-full text-caption text-muted-foreground [overflow-wrap:anywhere] sm:col-span-full">{tx.note}</span>}
        </div>;
      })}
    </div>
  </div>;
}
