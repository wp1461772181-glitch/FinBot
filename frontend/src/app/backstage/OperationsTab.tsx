import { listOperations, type OperationItem } from "../../api/backstage";
import { operationRow, type OperationRow } from "../../backstage-view.mjs";
import { useLocale } from "../../i18n";
import { BackstageTable, PagedFooter, Status, TabState, type Column } from "./BackstageTable";
import { usePaged } from "./use-paged";
import { useWords } from "./words";

/** 操作记录: the confirmation cards the assistant proposed, newest first: what it asked to do, how the card ended, when it was decided and what came of it.  A lapsed card nobody touched says so. */
export function OperationsTab() {
  const { t } = useLocale();
  const w = useWords();
  const list = usePaged<OperationItem, Awaited<ReturnType<typeof listOperations>>>((before, signal) => listOperations(before, signal), "operations");
  const rows = list.items.map(item => operationRow(item, undefined, w));
  const columns: Column<OperationRow>[] = [
    { key: "time", header: t("时间（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span> },
    { key: "bot", header: "bot", cell: row => row.bot },
    { key: "what", header: t("操作"), className: "sm:w-[34%]", wide: true, cell: row => <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ink">{row.what}</span>{row.detail && <span className="text-caption text-muted-foreground">{row.detail}</span>}</span> },
    { key: "status", header: t("状态"), cell: row => <Status status={row.status} /> },
    { key: "decided", header: t("处理时间（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.decided_at}</span> },
    { key: "result", header: t("结果"), cell: row => row.result },
  ];
  return <div data-testid="operations-tab" className="flex min-w-0 flex-col gap-3">
    <TabState loading={list.loading && rows.length === 0} error={list.error} empty={!list.loading && rows.length === 0} onRetry={() => void list.reload()}
      emptyTitle={t("还没有确认卡片的记录。")} emptyDescription={t("助手提出需要你点头的操作时，卡片会记在这里。")} />
    {rows.length > 0 && <>
      <BackstageTable testId="operations-table" label={t("操作记录")} columns={columns} rows={rows} rowKey={row => row.id} />
      <PagedFooter hasMore={Boolean(list.next)} loading={list.more} error={list.moreError} onMore={() => void list.loadMore()} />
    </>}
  </div>;
}
