import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useLocale } from "../../i18n";
import type { PortfolioTransaction } from "../../api/portfolio-ledger";
import { RecordList } from "./RecordList";

/** A long ledger shows its newest records first and the rest on request, so the page does not become a wall. */
export const LEDGER_PAGE = 50;

/**
 * 全部流水 (the old page's 记录 list, kept): every record of the account, including the ones that belong to no symbol (入金, 出金).  It is a section under the
 * positions, not a tab: the records are what the numbers above were worked out from, so they are read straight after them.  Each record can be deleted here
 * too, with the same question first.
 */
export function LedgerSection({ transactions, busy, onDelete }: { transactions: PortfolioTransaction[]; busy: boolean; onDelete: (tx: PortfolioTransaction, anchor: string) => void }) {
  const { t } = useLocale();
  const [shown, setShown] = useState(LEDGER_PAGE);
  const visible = transactions.slice(0, shown);
  return <section aria-labelledby="pf-ledger-all" data-testid="portfolio-ledger" className="flex min-w-0 flex-col gap-2">
    <div className="flex flex-wrap items-baseline gap-x-3">
      <h2 id="pf-ledger-all" tabIndex={-1} className="text-title-s text-ink outline-none">{t("全部流水")}</h2>
      <span className="font-mono text-caption text-muted-foreground">{transactions.length}</span>
    </div>
    {transactions.length === 0
      ? <p data-testid="portfolio-ledger-empty" className="text-small text-muted-foreground">{t("还没有记录。")}</p>
      : <div className="rounded-md border border-line bg-surface px-3 py-2 xl:px-4 xl:py-3">
        <RecordList records={visible} withSymbol busy={busy} onDelete={onDelete} anchor="pf-ledger-all" label={t("全部流水")} />
        {transactions.length > shown && <div className="flex justify-center pt-2"><Button type="button" variant="outline" size="sm" className="max-sm:h-11" onClick={() => setShown(n => n + LEDGER_PAGE)}>{t("显示更多")}</Button></div>}
      </div>}
  </section>;
}
