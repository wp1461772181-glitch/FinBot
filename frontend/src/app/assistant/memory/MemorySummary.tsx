import { useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { downloadMemoryExport, type MemoryCounts, type MemoryJob } from "../../../api/memory-overview";
import { useLocale } from "../../../i18n";
import { jobLine, jobOutcome, summaryLine } from "../../../memory-overview.mjs";

/**
 * The head of 它眼中的你: one sentence on what the page is, how much the system keeps (every count, zeros included), when it will next tidy its memory, and 导出 (one file of everything,
 * JSON to keep or Markdown to read).  `countsFailed` / `jobsFailed`: that part could not be read; the rest of the head still shows.
 */
export function MemorySummary({ counts, jobs, countsFailed, jobsFailed, loading, onReload }: { counts: MemoryCounts | null; jobs: MemoryJob[] | null; countsFailed: boolean; jobsFailed: boolean; loading: boolean; onReload: () => Promise<void> }) {
  const { t, locale } = useLocale();
  const [exporting, setExporting] = useState<"json" | "md" | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const items = summaryLine(counts);

  async function download(format: "json" | "md") {
    setExporting(format); setFailure(null);
    try { await downloadMemoryExport(format); }
    catch (error) { setFailure(error); }
    finally { setExporting(null); }
  }

  return <section data-testid="memory-summary" aria-labelledby="memory-summary-title" className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-4">
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-1 basis-80 flex-col gap-1">
        <h2 id="memory-summary-title" className="text-title-s text-ink">{t("它眼中的你")}</h2>
        <p data-testid="memory-summary-note" className="max-w-3xl text-small text-ink-2">{t("这是系统记得的关于你的一切，以及它的推测。都可以改、删，也可以整体导出。推测只影响回答的详略和先后，不影响结论。")}</p>
      </div>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild><Button type="button" variant="outline" data-testid="memory-export" disabled={exporting !== null} aria-busy={exporting !== null} className="max-sm:h-11"><Download aria-hidden="true" />{t("导出")}</Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem data-testid="memory-export-json" onSelect={() => void download("json")}>{t("导出 JSON（完整）")}</DropdownMenuItem>
          <DropdownMenuItem data-testid="memory-export-md" onSelect={() => void download("md")}>{t("导出 Markdown（好读）")}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
    {failure != null && <ErrorBar error={failure} />}
    {countsFailed && <ErrorBar message={t("这一部分暂时读不出来。")} onRetry={() => void onReload()} retrying={loading} />}
    {!counts && !countsFailed && loading && <DelayedSkeleton><div role="status" aria-busy="true"><span className="sr-only">{t("正在读取")}</span><Skeleton className="h-6 w-full" /></div></DelayedSkeleton>}
    {items.length > 0 && <ul data-testid="memory-counts" className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-small text-ink-2">{items.map(item => <li key={item.key} data-testid="memory-count" data-key={item.key} className="flex items-baseline gap-1.5">
      <span>{t(item.label)}</span><span className="font-mono text-body font-medium text-ink">{item.value}</span>
    </li>)}</ul>}
    {jobsFailed && <ErrorBar message={t("这一部分暂时读不出来。")} onRetry={() => void onReload()} retrying={loading} />}
    {jobs && jobs.length === 0 && <p data-testid="memory-jobs-empty" className="m-0 text-small text-muted-foreground">{t("记忆整理还没有排上日程。")}</p>}
    {jobs && jobs.length > 0 && <ul data-testid="memory-jobs" className="m-0 flex list-none flex-col gap-1 p-0">{jobs.map(job => <li key={job.job} data-testid="memory-job" data-job={job.job} className="text-small text-ink-2">
      {jobLine(job, locale)}{jobOutcome(job, locale) && <span className="text-muted-foreground"> · {jobOutcome(job, locale)}</span>}
    </li>)}</ul>}
  </section>;
}
