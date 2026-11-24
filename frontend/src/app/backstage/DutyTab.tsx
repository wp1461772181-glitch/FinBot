import { useRef, useState } from "react";
import { listDuty, type DutyItem } from "../../api/backstage";
import { dutyModeLine, dutyRow, type DutyRow } from "../../backstage-view.mjs";
import { colon, useLocale } from "../../i18n";
import { AnswerDrawer } from "./AnswerDrawer";
import { BackstageTable, PagedFooter, Status, TabState, type Column } from "./BackstageTable";
import { usePaged } from "./use-paged";
import { useWords } from "./words";

/**
 * 值班: each time a market alert woke the agent, newest first: what the alert said, what the agent decided and why, the message when it chose to tell you, and whether that went out.
 * A line opens the wake turn's course in the same drawer as an answer.  Nothing here writes.
 */
export function DutyTab() {
  const { t } = useLocale();
  const w = useWords();
  const list = usePaged<DutyItem, Awaited<ReturnType<typeof listDuty>>>((before, signal) => listDuty(before, signal), "duty");
  const [openId, setOpenId] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const open = (id: string | null) => { if (!id) return; opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setOpenId(id); };
  const rows = list.items.map(item => dutyRow(item, undefined, w));
  const modeLine = list.extra ? dutyModeLine(list.extra.mode) : "";
  const columns: Column<DutyRow>[] = [
    { key: "time", header: t("时间（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span> },
    { key: "symbol", header: t("代码"), cell: row => <span className="font-mono">{row.symbol}</span> },
    { key: "what", header: t("发生了什么"), className: "sm:w-[24%]", wide: true, cell: row => row.open
      ? <button type="button" data-testid="duty-open" onClick={event => { event.stopPropagation(); open(row.open); }} className="line-clamp-2 text-left text-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{row.what}</button>
      : <span className="line-clamp-2 text-ink">{row.what}</span> },
    { key: "decision", header: t("决定"), className: "whitespace-nowrap", cell: row => <Status status={row.decision} /> },
    { key: "reason", header: t("理由"), className: "sm:w-[22%]", wide: true, cell: row => <span className="line-clamp-3 [overflow-wrap:anywhere]">{row.reason || "—"}</span> },
    { key: "message", header: t("发给你的消息"), className: "sm:w-[22%]", wide: true, cell: row => row.message
      ? <span className="flex min-w-0 flex-col gap-1"><span className="line-clamp-3 [overflow-wrap:anywhere] text-ink">{row.message}</span>{row.delivery && <span data-testid="duty-delivery" className="text-caption text-muted-foreground">{t(row.delivery)}</span>}</span>
      : "—" },
    { key: "mode", header: t("模式"), cell: row => <span className="inline-flex whitespace-nowrap rounded-full border border-line px-2 text-caption text-muted-foreground">{row.mode}</span> },
  ];
  return <div data-testid="duty-tab" className="flex min-w-0 flex-col gap-3">
    {modeLine && <p data-testid="duty-mode" className="text-small text-ink-2">{t(modeLine)}</p>}
    <TabState loading={list.loading && rows.length === 0} error={list.error} empty={!list.loading && rows.length === 0} onRetry={() => void list.reload()}
      emptyTitle={t("还没有值班的记录。")} emptyDescription={t("盯盘提醒一出现就会唤醒助手，它的判断会记在这里。")} />
    {rows.length > 0 && <>
      <BackstageTable testId="duty-table" label={t("值班记录")} columns={columns} rows={rows} rowKey={row => row.id} onOpen={row => open(row.open)} />
      <PagedFooter hasMore={Boolean(list.next)} loading={list.more} error={list.moreError} onMore={() => void list.loadMore()} />
      <p className="sr-only" aria-live="polite">{`${t("已显示")}${colon()}${rows.length}`}</p>
    </>}
    <AnswerDrawer id={openId} onClose={() => setOpenId(null)} returnFocus={() => { if (opener.current?.isConnected) opener.current.focus(); }} />
  </div>;
}
