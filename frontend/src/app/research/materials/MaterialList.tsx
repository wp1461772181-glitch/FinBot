import { useEffect, useRef } from "react";
import { FileText, Newspaper } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { cn } from "@/lib/utils";
import type { MaterialItem } from "../../../types";
import { formatDate as formatLocalizedDate, getLocalePreference, translatePhrase, useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { PAGE_SIZE, SOURCE_PHRASE, isNarrowed, pageRange, statusKind, statusPhrase, type Filters } from "./materials-model.mjs";

/** `key` names the request a ready page answers (the filters, the offset and the refresh count), so a reader of the page can tell when it is the page that was asked for. */
export type PageState = { kind: "loading" } | { kind: "ready"; items: MaterialItem[]; total: number; key?: string } | { kind: "error"; message: string };

function formatDate(value: string | null) {
  if (!value) return getLocalePreference() === "en-US" ? "Unknown" : "未知";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value.slice(0, 10) : formatLocalizedDate(date, getLocalePreference(), "UTC");
}

/**
 * The list of the library (design 4.7): a row per material with its title, kind, publication time and an analysis status badge (words from the old table,
 * one fixed icon and tone per status); the chosen row is marked; a page is ten rows and Previous / Next turn it.  A row that the address named is scrolled into view.
 */
export function MaterialList({ symbol, page, filters, offset, selected, scrollTo, showSymbol, onSelect, onOffset, onRetry, onClear }: {
  symbol: string; page: PageState; filters: Filters; offset: number; selected: MaterialItem | null; scrollTo: string | null; showSymbol: boolean;
  onSelect: (item: MaterialItem) => void; onOffset: (offset: number) => void; onRetry: () => void; onClear: () => void;
}) {
  const { t } = useLocale();
  const chosen = useRef<HTMLButtonElement | null>(null);
  const key = selected ? `${selected.source_type}:${selected.source_id}` : "";
  // Only a row the address named is brought into view (a press on a row never moves the list).
  useEffect(() => { if (scrollTo && key === scrollTo) chosen.current?.scrollIntoView?.({ block: "center" }); }, [key, scrollTo, page.kind]);
  if (page.kind === "loading") return <DelayedSkeleton><SkeletonRows rows={6} /></DelayedSkeleton>;
  if (page.kind === "error") return <ErrorBar message={page.message} onRetry={onRetry} />;
  if (page.items.length === 0) return isNarrowed(filters)
    ? <EmptyState title={t("没有符合筛选条件的材料")} description={t("换一个筛选条件，或清除筛选看全部材料。")} action={{ label: t("清除筛选"), onClick: onClear }} className="rounded-md border border-dashed border-line" />
    : <EmptyState title={t("这家公司还没有材料")} description={t("没有匹配材料。可在证据页上传媒体材料，或扫描 SEC 资料。")} action={{ label: t("上传媒体材料"), to: paths.evidenceIndex({ symbol, upload: true }) }} className="rounded-md border border-dashed border-line" />;
  return <div className="flex min-w-0 flex-col gap-3">
    <ul data-testid="material-list" aria-label={`${symbol} ${t("的研究材料")}`} className="m-0 flex list-none flex-col gap-1.5 p-0">
      {page.items.map(item => {
        const isSelected = selected?.source_id === item.source_id && selected.source_type === item.source_type;
        const Icon = item.source_type === "official_filing" ? FileText : Newspaper;
        return <li key={`${item.source_type}:${item.source_id}`}>
          <button ref={isSelected ? chosen : undefined} type="button" data-testid="material-row" data-source-id={item.source_id} data-source-type={item.source_type} data-status={item.analysis_status} data-selected={isSelected ? "" : undefined} aria-current={isSelected ? "true" : undefined} onClick={() => onSelect(item)}
            className={cn("flex w-full min-w-0 flex-col gap-1 rounded-md border px-3 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11", isSelected ? "border-brand bg-brand-soft" : "border-line bg-surface hover:bg-sunken")}>
            <span className="flex min-w-0 items-start justify-between gap-2"><strong className="min-w-0 text-small font-medium text-ink [overflow-wrap:anywhere]">{item.title}</strong><StatusBadge kind={statusKind(item.analysis_status)} className="shrink-0">{translatePhrase(statusPhrase(item))}</StatusBadge></span>
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 text-caption text-muted-foreground"><Icon aria-hidden="true" className="size-3.5 shrink-0" />{showSymbol && <span className="font-mono">{item.symbol}</span>}<span>{t(SOURCE_PHRASE[item.source_type])}</span><span>· {t("发布")} {formatDate(item.published_at)}</span></span>
            <span className="text-caption text-muted-foreground">{item.latest_analysis_version_no ? `${t("AI 分析")} v${item.latest_analysis_version_no}` : t("尚无 AI 分析记录")}</span>
          </button>
        </li>;
      })}
    </ul>
    <div data-testid="material-pagination" className="flex items-center justify-between gap-2">
      <Button type="button" variant="outline" size="sm" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))} className="max-sm:h-11">{t("上一页")}</Button>
      <span data-testid="material-range" className="font-mono text-caption text-muted-foreground">{pageRange(offset, page.total)}{page.total ? "" : ` ${t("条")}`}</span>
      <Button type="button" variant="outline" size="sm" disabled={offset + PAGE_SIZE >= page.total} onClick={() => onOffset(offset + PAGE_SIZE)} className="max-sm:h-11">{t("下一页")}</Button>
    </div>
  </div>;
}

