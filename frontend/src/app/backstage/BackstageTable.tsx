import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import type { BadgeStatus, Cost } from "../../backstage-view.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";

/** `wide`: on a phone the cell takes the whole width of the card (a question, a sentence); the others sit two to a line. */
export type Column<Row> = { key: string; header: string; cell: (row: Row) => ReactNode; className?: string; wide?: boolean };

/**
 * A table that becomes stacked rows below the small breakpoint (640px): each cell then carries its column's name in front of the value, so a phone reads
 * "时间  11-13 01:50" line by line instead of scrolling sideways.  `onOpen` makes a row open its detail (the first column's button is the keyboard way in).
 */
export function BackstageTable<Row>({ label, columns, rows, rowKey, onOpen, testId, rowClass }: {
  label: string; columns: Column<Row>[]; rows: Row[]; rowKey: (row: Row) => string; onOpen?: (row: Row) => void; testId: string; rowClass?: (row: Row) => string | undefined;
}) {
  return <table data-testid={testId} aria-label={label} className="w-full min-w-0 border-collapse text-small max-sm:block">
    <thead className="max-sm:sr-only">
      <tr className="border-b border-line text-left text-caption text-muted-foreground">
        {columns.map(column => <th key={column.key} scope="col" className={cn("px-3 py-2 font-medium", column.className)}>{column.header}</th>)}
      </tr>
    </thead>
    <tbody className="max-sm:block">
      {rows.map(row => <tr key={rowKey(row)} data-testid="backstage-row" onClick={onOpen ? () => onOpen(row) : undefined}
        className={cn("border-b border-line align-top max-sm:mb-2 max-sm:grid max-sm:grid-cols-2 max-sm:gap-x-4 max-sm:rounded-md max-sm:border max-sm:bg-surface max-sm:p-3", onOpen && "cursor-pointer hover:bg-sunken", rowClass?.(row))}>
        {columns.map(column => <td key={column.key} data-label={column.header}
          className={cn("px-3 py-2 max-sm:flex max-sm:min-w-0 max-sm:flex-col max-sm:gap-0.5 max-sm:px-0 max-sm:py-1 max-sm:before:text-caption max-sm:before:text-muted-foreground max-sm:before:content-[attr(data-label)]", column.wide && "max-sm:col-span-2", column.className)}>
          <span className="min-w-0">{column.cell(row)}</span>
        </td>)}
      </tr>)}
    </tbody>
  </table>;
}

/** A status as the badge shows it. */
export function Status({ status }: { status: BadgeStatus }) {
  const { t } = useLocale();
  return <StatusBadge kind={status.kind}>{t(status.label)}</StatusBadge>;
}

/** A cost: the figure; 「未设价格」 for a call to a model with no price (never a made-up figure); a dash when nothing was called. */
export function CostText({ cost, className }: { cost: Cost; className?: string }) {
  const { t } = useLocale();
  if (cost.kind === "amount") return <span className={cn("font-mono tabular-nums", className)}>{cost.amount}</span>;
  if (cost.kind === "unpriced") return <Link to={paths.settings("models")} title={t("去设置里给这个模型填价格")} className={cn("text-action underline-offset-2 hover:underline", className)}>{t("未设价格")}</Link>;
  return <span className={cn("text-muted-foreground", className)}>—</span>;
}

/** What a tab shows while it has no rows: a skeleton while it is read, the error with 重试, or the empty sentence.  Returns null when there are rows to show. */
export function TabState({ loading, error, empty, onRetry, emptyTitle, emptyDescription }: {
  loading: boolean; error: unknown; empty: boolean; onRetry: () => void; emptyTitle: string; emptyDescription?: string;
}) {
  if (error) return <ErrorBar error={error} onRetry={onRetry} retrying={loading} />;
  if (loading) return <DelayedSkeleton><div data-testid="backstage-loading"><SkeletonRows rows={6} /></div></DelayedSkeleton>;
  if (empty) return <div data-testid="backstage-empty"><EmptyState title={emptyTitle} description={emptyDescription} /></div>;
  return null;
}

/** The end of a paged list: the next page is read when this scrolls into view (and by 加载更多, for a keyboard or a browser without the observer); a failed read keeps the rows and offers 重试. */
export function PagedFooter({ hasMore, loading, error, onMore }: { hasMore: boolean; loading: boolean; error: unknown; onMore: () => void }) {
  const { t } = useLocale();
  const sentinel = useRef<HTMLDivElement>(null);
  const more = useRef(onMore);
  more.current = onMore;
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasMore || error || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) more.current(); }, { rootMargin: "240px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, error, loading]);
  if (error) return <ErrorBar error={error} onRetry={onMore} retrying={loading} />;
  if (!hasMore) return null;
  return <div ref={sentinel} data-testid="backstage-more" className="flex justify-center py-3">
    <button type="button" onClick={onMore} disabled={loading} aria-busy={loading}
      className="inline-flex h-9 items-center rounded-sm border border-line-strong bg-background px-4 text-small text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 max-sm:h-11">{loading ? t("正在读取") : t("加载更多")}</button>
  </div>;
}
