import { useState } from "react";
import { cn } from "@/lib/utils";
import { listDeliveries, sendFeedback, type DeliveryItem } from "../../api/backstage";
import { deliveryRow, FEEDBACK_CHOICES, FEEDBACK_FAILED, type DeliveryRow, type Verdict } from "../../backstage-view.mjs";
import { useLocale } from "../../i18n";
import { BackstageTable, PagedFooter, Status, TabState, type Column } from "./BackstageTable";
import { usePaged } from "./use-paged";
import { useWords } from "./words";

/** 提醒投递: the outbox, newest first: which reminder went out through which channel, whether it was sent, and whether you acknowledged it.
 * A duty or brief message also takes your 「有用／没用」. */
export function DeliveriesTab() {
  const { t } = useLocale();
  const w = useWords();
  const list = usePaged<DeliveryItem, Awaited<ReturnType<typeof listDeliveries>>>((before, signal) => listDeliveries(before, signal), "deliveries");
  const rows = list.items.map(item => deliveryRow(item, undefined, w));
  // What was pressed on this page (by group): it wins over the verdict the list was read with; a failed request is marked until the next press.
  const [chosen, setChosen] = useState<Record<string, Verdict>>({});
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const press = async (group: string, verdict: Verdict) => {
    setBusy(state => ({ ...state, [group]: true }));
    setFailed(state => ({ ...state, [group]: false }));
    try {
      await sendFeedback(group, verdict);
      setChosen(state => ({ ...state, [group]: verdict }));
    } catch {
      setFailed(state => ({ ...state, [group]: true }));
    } finally {
      setBusy(state => ({ ...state, [group]: false }));
    }
  };
  const feedback = (row: DeliveryRow) => {
    if (!row.feedback) return null;
    const { group } = row.feedback;
    const current = chosen[group] ?? row.feedback.verdict;
    return <span data-testid="delivery-feedback" className="mt-1 flex items-center gap-1.5">
      {FEEDBACK_CHOICES.map(choice => <button key={choice.verdict} type="button" aria-pressed={current === choice.verdict} disabled={busy[group]}
        onClick={event => { event.stopPropagation(); if (current !== choice.verdict) void press(group, choice.verdict); }}
        className={cn("inline-flex h-7 items-center rounded-sm border px-2 text-caption outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 max-sm:h-9",
          current === choice.verdict ? "border-brand bg-brand-soft font-medium text-ink" : "border-line bg-surface text-ink-2 hover:bg-sunken")}>{t(choice.label)}</button>)}
      {failed[group] && <span role="status" className="text-caption text-danger">{t(FEEDBACK_FAILED)}</span>}
    </span>;
  };
  const columns: Column<DeliveryRow>[] = [
    { key: "time", header: t("时间（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span> },
    { key: "source", header: t("来源"), cell: row => t(row.source) },
    { key: "channel", header: t("渠道"), cell: row => t(row.channel) },
    { key: "text", header: t("内容"), className: "sm:w-[34%]", wide: true, cell: row => <>
      <span className="line-clamp-2 [overflow-wrap:anywhere] text-ink">{row.text || "—"}</span>
      {feedback(row)}
    </> },
    { key: "status", header: t("状态"), cell: row => <Status status={row.status} /> },
    { key: "acked", header: t("已确认（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.acked}</span> },
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
