import { useRef, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { confirm } from "@/components/state/confirm";
import { errorReason } from "@/components/state/error-message";
import { notify } from "@/components/state/notify";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { addPortfolioTransaction, deletePortfolioTransaction, putPortfolioCash, putPortfolioPlan, type PortfolioTransaction } from "../../api/portfolio-ledger";
import { useLocale } from "../../i18n";
import { blankEntry, warningLabels, type PortfolioEntryForm, type PortfolioPlanForm } from "../../portfolio-items.mjs";
import { LedgerSection } from "./LedgerSection";
import { PositionPanel } from "./PositionPanel";
import { PositionRow, PositionsHeader } from "./PositionsTable";
import { RecordDialog } from "./RecordDialog";
import { SummaryRow } from "./SummaryRow";
import { planDraft } from "./portfolio-view.mjs";
import { usePortfolio, useResearchLists } from "./use-portfolio";

/** The shape of the page while it is read: a row of tiles and a few rows of the table. */
function PortfolioSkeleton() {
  const { t } = useLocale();
  return <div role="status" aria-busy="true" data-testid="portfolio-skeleton" className="flex flex-col gap-4">
    <span className="sr-only">{t("正在读取")}</span>
    <div className="grid grid-cols-2 gap-2 xl:grid-cols-[minmax(0,1.5fr)_repeat(5,minmax(0,1fr))] xl:gap-3">
      {Array.from({ length: 6 }, (_, i) => <div key={i} className={`flex flex-col gap-2 rounded-md border border-line bg-surface p-3 ${i < 2 ? "col-span-2 xl:col-span-1" : ""}`}><Skeleton className="h-3 w-1/3" /><Skeleton className={i === 0 ? "h-8 w-3/4" : "h-5 w-2/3"} /></div>)}
    </div>
    <div className="flex flex-col gap-2 rounded-md border border-line bg-surface p-3">
      <Skeleton className="h-3 w-full" />
      {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-5 w-full" />)}
    </div>
  </div>;
}

/**
 * 持仓 (#/portfolio, design 4.9): the reader's own ledger.  The key numbers on top, the positions as a table (a card each on a phone) that opens to the plan, the
 * records and the research on that symbol, and the whole ledger under it.  It is a book the reader keeps: the assistant does not trade for them and nothing on
 * this page places an order.  Every figure is the server's, shown through portfolio-items.mjs; the writes are the old page's requests, unchanged.
 */
export function PortfolioPage() {
  const { t } = useLocale();
  const { data, error, loading, reload } = usePortfolio();
  const lists = useResearchLists(data?.positions.map(p => p.symbol) ?? []);
  // One position is open at a time, so the research area (and its one disclaimer) is on screen once.  The plan drafts are kept here, per symbol, whether or not their row is open.
  const [open, setOpen] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, PortfolioPlanForm>>({});
  const [recording, setRecording] = useState(false);
  const [entry, setEntry] = useState<PortfolioEntryForm>(() => blankEntry());
  const [entryError, setEntryError] = useState("");
  const [removing, setRemoving] = useState(false);
  const recordButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  /** A write: the old requests, then the page reads the ledger again and says what happened.  A failed read-back does not turn a good write into a failure (the page shows its own error bar). */
  async function write(work: () => Promise<unknown>, done: string) {
    const result = await work() as { warnings?: string[] } | undefined;
    await reload();
    const warned = warningLabels(result?.warnings).map(w => t(w)).join(" ");
    notify.success(t(done), { id: `portfolio:${done}`, ...(warned ? { description: warned } : {}) });
  }
  const saveCash = (value: string) => write(() => putPortfolioCash(value), "可用资金已更新。");
  const savePlan = (symbol: string, body: Parameters<typeof putPortfolioPlan>[1]) =>
    write(() => putPortfolioPlan(symbol, body), "计划已保存。").then(() => setDrafts(current => { const { [symbol]: _gone, ...rest } = current; return rest; }));
  const submitEntry = (body: Record<string, string>) =>
    write(() => addPortfolioTransaction(body), "已记录。").then(() => { setRecording(false); setEntry(blankEntry(entry.kind)); setEntryError(""); });
  async function removeRecord(tx: PortfolioTransaction, anchor: string) {
    const yes = await confirm({ title: t("删除这一笔记录？"), description: t("持仓和可用资金会按剩下的记录重新计算。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (!yes) return;
    setRemoving(true);
    try { await write(() => deletePortfolioTransaction(tx.id), "已删除。"); }
    catch (cause) { notify.error(errorReason(cause, t), { id: "portfolio:delete-failed" }); }
    finally { setRemoving(false); requestAnimationFrame(() => document.getElementById(anchor)?.focus()); }
  }
  const openRecord = () => {
    opener.current = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
    setEntryError(""); setRecording(true);
  };
  const returnFocus = () => { const back = opener.current?.isConnected ? opener.current : recordButton.current; back?.focus(); };

  return <main data-testid="portfolio-page" aria-labelledby="portfolio-title" className="mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 id="portfolio-title" className="text-title-m text-ink">{t("持仓")}</h1>
        <p className="max-w-2xl text-small text-muted-foreground">{t("手填或在对话里告诉助理（会先出确认卡）。这里只记录你自己的持仓和计划，不是买卖建议；第一版不支持导入券商对账单。")}</p>
      </div>
      {data && <Button ref={recordButton} type="button" data-testid="record-open" className="max-sm:h-11" onClick={openRecord}><Plus aria-hidden="true" />{t("记一笔")}</Button>}
    </header>
    {!data && loading && <DelayedSkeleton><PortfolioSkeleton /></DelayedSkeleton>}
    {!data && !loading && error != null && <div data-testid="portfolio-error"><ErrorBar error={error} onRetry={() => void reload()} retrying={loading} /></div>}
    {data && <>
      {error != null && <ErrorBar error={error} onRetry={() => void reload()} retrying={loading} />}
      <SummaryRow data={data} onSaveCash={saveCash} />
      {data.positions.length === 0
        ? <div data-testid="portfolio-empty" className="rounded-md border border-line bg-surface">
          <EmptyState title={t("还没有持仓")} description={t("持仓是你自己记的账，助理不会替你交易。点「记第一笔」添加，或对助理说「我买了 100 股 INTC，成本 80」。")} action={{ label: t("记第一笔"), onClick: openRecord }} />
        </div>
        : <section aria-label={t("持仓列表")} className="flex flex-col gap-2">
          <div role="table" aria-label={t("持仓列表")} data-testid="portfolio-table" className="flex flex-col gap-2 xl:gap-0 xl:rounded-md xl:border xl:border-line xl:bg-surface">
            <PositionsHeader />
            {data.positions.map(position => <PositionRow key={position.symbol} position={position} open={open === position.symbol} unsaved={planDraft(position.plan, drafts[position.symbol]).changed}
              onToggle={() => setOpen(current => current === position.symbol ? null : position.symbol)}
              panel={<PositionPanel position={position} transactions={data.transactions} draft={drafts[position.symbol]} lists={lists} busy={removing}
                onDraft={(symbol, form) => setDrafts(current => ({ ...current, [symbol]: form }))} onSavePlan={savePlan} onDelete={removeRecord} />} />)}
          </div>
        </section>}
      <LedgerSection transactions={data.transactions} busy={removing} onDelete={removeRecord} />
    </>}
    {recording && <RecordDialog entry={entry} setEntry={setEntry} error={entryError} setError={setEntryError} onSubmit={submitEntry} onClose={() => setRecording(false)} returnFocus={returnFocus} />}
  </main>;
}
