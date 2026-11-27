import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Input } from "@/components/ui/input";
import { listMemoryChanges, type MemoryChangeItem } from "../../api/backstage";
import { MEMORY_BYS, MEMORY_CHANGES, MEMORY_FILTER_DEFAULTS, MEMORY_NOTE, MEMORY_TARGETS, memoryRow, type MemoryFilters, type MemoryRow } from "../../backstage-view.mjs";
import { colon, useLocale } from "../../i18n";
import { BackstageTable, PagedFooter, TabState, type Column } from "./BackstageTable";
import { usePaged } from "./use-paged";
import { useWords } from "./words";

const field = "h-9 rounded-sm border border-input bg-background px-2 text-small text-ink outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 max-sm:h-11";

function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => { const timer = window.setTimeout(() => setSettled(value), delay); return () => window.clearTimeout(timer); }, [value, delay]);
  return settled;
}

/**
 * 记忆变更: every change to what the assistant keeps about the owner (his memory and his views of companies), newest first: what changed, who changed it and on
 * what basis.  Filters on top (对象, 变更, 谁改的, a search over the words and the reason), the list pages itself as it scrolls, a change that came from a
 * conversation links to it.  Nothing here writes.
 */
export function MemoryTab() {
  const { t } = useLocale();
  const w = useWords();
  const [filters, setFilters] = useState<MemoryFilters>({ ...MEMORY_FILTER_DEFAULTS });
  const searched = useDebounced(filters.q, 350);
  const applied = useMemo(() => ({ ...filters, q: searched }), [filters, searched]);
  const key = JSON.stringify(applied);
  const list = usePaged<MemoryChangeItem, Awaited<ReturnType<typeof listMemoryChanges>>>((before, signal) => listMemoryChanges(applied, before, signal), key);
  const set = (patch: Partial<MemoryFilters>) => setFilters(current => ({ ...current, ...patch }));

  const rows = list.items.map(item => memoryRow(item, undefined, w));
  const columns: Column<MemoryRow>[] = [
    { key: "time", header: t("时间（本地时间）"), cell: row => <span className="flex flex-col gap-0.5"><span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span>
      {row.reconstructed && <span data-testid="memory-reconstructed" className="text-caption text-muted-foreground">{row.reconstructed}</span>}</span> },
    { key: "what", header: t("对象"), cell: row => row.what },
    { key: "action", header: t("变更"), cell: row => <span className="whitespace-nowrap">{row.action}</span> },
    { key: "content", header: t("内容"), className: "sm:w-[30%]", wide: true, cell: row => <span className={row.gone ? "text-muted-foreground" : "text-ink"}>{row.content}</span> },
    { key: "by", header: t("谁改的"), cell: row => <span className="whitespace-nowrap">{row.by}</span> },
    { key: "basis", header: t("依据"), className: "sm:w-[26%]", wide: true, cell: row => <span className="flex min-w-0 flex-col gap-0.5">
      {row.basis.map((part, index) => <span key={index} className="text-caption text-muted-foreground">{part}</span>)}
      {row.link && <Link to={row.link.to} data-testid="memory-conversation" className="text-caption text-action underline-offset-2 hover:underline">{row.link.label}</Link>}
      {!row.basis.length && !row.link && <span className="text-muted-foreground">—</span>}
    </span> },
  ];
  const filtered = Boolean(filters.target || filters.change || filters.by || searched);

  return <div data-testid="memory-tab" className="flex min-w-0 flex-col gap-3">
    <div role="search" aria-label={t("筛选记忆变更")} className="flex flex-wrap items-end gap-x-3 gap-y-2">
      <label className="flex flex-col gap-1 text-caption text-muted-foreground">{t("对象")}
        <select data-testid="filter-target" value={filters.target} onChange={event => set({ target: event.target.value })} className={field}>
          <option value="">{t("全部")}</option>
          {MEMORY_TARGETS.map(choice => <option key={choice.value} value={choice.value}>{t(choice.label)}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-caption text-muted-foreground">{t("变更")}
        <select data-testid="filter-change" value={filters.change} onChange={event => set({ change: event.target.value })} className={field}>
          <option value="">{t("全部")}</option>
          {MEMORY_CHANGES.map(choice => <option key={choice.value} value={choice.value}>{t(choice.label)}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-caption text-muted-foreground">{t("谁改的")}
        <select data-testid="filter-by" value={filters.by} onChange={event => set({ by: event.target.value })} className={field}>
          <option value="">{t("全部")}</option>
          {MEMORY_BYS.map(choice => <option key={choice.value} value={choice.value}>{t(choice.label)}</option>)}
        </select>
      </label>
      <label className="flex min-w-0 flex-1 basis-56 flex-col gap-1 text-caption text-muted-foreground">{t("搜索内容和原因")}
        <Input type="search" data-testid="filter-q" value={filters.q} maxLength={100} onChange={event => set({ q: event.target.value })} placeholder={t("搜索内容和原因")} className="max-sm:h-11" />
      </label>
    </div>
    <TabState loading={list.loading && rows.length === 0} error={list.error} empty={!list.loading && rows.length === 0} onRetry={() => void list.reload()}
      emptyTitle={filtered ? t("没有符合筛选的变更。") : t("还没有记忆变更的记录。")}
      emptyDescription={t("记下、修改、归档或删除一条记忆或看法时，这里就多一行。")} />
    {rows.length > 0 && <>
      <BackstageTable testId="memory-table" label={t("记忆变更记录")} columns={columns} rows={rows} rowKey={row => row.id} />
      <PagedFooter hasMore={Boolean(list.next)} loading={list.more} error={list.moreError} onMore={() => void list.loadMore()} />
      <p className="sr-only" aria-live="polite">{`${t("已显示")}${colon()}${rows.length}`}</p>
    </>}
    <p data-testid="memory-note" role="note" className="text-caption text-muted-foreground">{t(MEMORY_NOTE)}</p>
  </div>;
}
