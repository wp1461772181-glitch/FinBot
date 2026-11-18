import { useLocale } from "../../i18n";
import type { PortfolioPlanForm } from "../../portfolio-items.mjs";
import type { PortfolioPosition, PortfolioTransaction } from "../../api/portfolio-ledger";
import { Pnl } from "./Pnl";
import { PlanForm } from "./PlanForm";
import { RecordList } from "./RecordList";
import { ResearchRecord } from "./ResearchRecord";
import { planDraft, recordsOf } from "./portfolio-view.mjs";
import type { ResearchLists } from "./use-portfolio";

/**
 * What a position opens to (design 4.9): 我的计划, 流水 (this symbol's records, each deletable), 研究记录.  On a wide screen the plan is the left column and the
 * other two stack on the right; on a phone they stack in that order.  The fact line at the top is the position's own 今日盈亏, which the old card had and the table has no column for.
 */
export function PositionPanel({ position, transactions, draft, lists, busy, onDraft, onSavePlan, onDelete }: {
  position: PortfolioPosition; transactions: PortfolioTransaction[]; draft: PortfolioPlanForm | undefined; lists: ResearchLists; busy: boolean;
  onDraft: (symbol: string, form: PortfolioPlanForm) => void;
  onSavePlan: (symbol: string, body: Parameters<React.ComponentProps<typeof PlanForm>["onSave"]>[0]) => Promise<unknown>;
  onDelete: (tx: PortfolioTransaction, anchor: string) => void;
}) {
  const { t } = useLocale();
  const symbol = position.symbol;
  const { form, changed } = planDraft(position.plan, draft);
  const records = recordsOf(transactions, symbol);
  const anchor = `pf-ledger-${symbol}`;
  return <div className="flex flex-col gap-4">
    <p className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-small text-ink-2">
      <span className="flex items-baseline gap-1.5">{t("今日盈亏")}{position.today_pnl_reference_only ? ` · ${t("仅供参考")}` : ""} <Pnl value={position.today_pnl} className="text-small" /></span>
    </p>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] xl:gap-x-8">
      <div className="xl:row-span-2"><PlanForm symbol={symbol} form={form} changed={changed} onChange={next => onDraft(symbol, next)} onSave={body => onSavePlan(symbol, body)} /></div>
      <section aria-labelledby={anchor} className="flex min-w-0 flex-col gap-1.5">
        <h4 id={anchor} tabIndex={-1} className="text-small font-medium text-ink outline-none">{t("流水")}</h4>
        {records.length === 0
          ? <p className="text-small text-muted-foreground">{t("这只股票还没有记录。")}</p>
          : <RecordList records={records} busy={busy} onDelete={onDelete} anchor={anchor} label={`${symbol} ${t("流水")}`} />}
      </section>
      <ResearchRecord symbol={symbol} lists={lists} />
    </div>
  </div>;
}
