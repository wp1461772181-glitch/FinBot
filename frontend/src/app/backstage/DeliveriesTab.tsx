import { listDeliveries, type DeliveryItem } from "../../api/backstage";
import { deliveryRow, type DeliveryRow } from "../../backstage-view.mjs";
import { useLocale } from "../../i18n";
import { BackstageTable, PagedFooter, Status, TabState, type Column } from "./BackstageTable";
import { usePaged } from "./use-paged";
import { useWords } from "./words";

/** 提醒投递: the outbox, newest first: which reminder went out through which channel, whether it was sent, and whether you acknowledged it. */
export function DeliveriesTab() {
  const { t } = useLocale();
  const w = useWords();
  const list = usePaged<DeliveryItem, Awaited<ReturnType<typeof listDeliveries>>>((before, signal) => listDeliveries(before, signal), "deliveries");
  const rows = list.items.map(item => deliveryRow(item, undefined, w));
  const columns: Column<DeliveryRow>[] = [
    { key: "time", header: t("时间"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span> },
    { key: "source", header: t("来源"), cell: row => t(row.source) },
    { key: "channel", header: t("渠道"), cell: row => t(row.channel) },
    { key: "text", header: t("内容"), className: "sm:w-[34%]", wide: true, cell: row => <span className="line-clamp-2 break-words text-ink">{row.text || "—"}</span> },
    { key: "status", header: t("状态"), cell: row => <Status status={row.status} /> },
    { key: "acked", header: t("已确认"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.acked}</span> },
  ];
  return <div data-testid="deliveries-tab" className="flex min-w-0 flex-col gap-3">
    <TabState loading={list.loading && rows.length === 0} error={list.error} empty={!list.loading && rows.length === 0} onRetry={() => void list.reload()}
      emptyTitle={t("还没有发出过提醒。")} emptyDescription={t("通过 Telegram 或微信发出的提醒会记在这里。")} />
    {rows.length > 0 && <>
      <BackstageTable testId="deliveries-table" label={t("提醒投递")} columns={columns} rows={rows} rowKey={row => row.id} />
      <PagedFooter hasMore={Boolean(list.next)} loading={list.more} error={list.moreError} onMore={() => void list.loadMore()} />
    </>}
  </div>;
}
