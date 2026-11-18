import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import type { TaskRun } from "../../api/tasks";
import { useLocale } from "../../i18n";
import { RunsTimeline } from "./RunsTimeline";

/** The last runs with their own states (skeleton, error bar, empty sentence); the 运行记录 tab and a bot's settings page both show it. */
export function RunsPane({ runs, error, loading, onRetry }: { runs: TaskRun[] | null; error: unknown; loading: boolean; onRetry: () => void }) {
  const { t } = useLocale();
  return <div data-testid="runs-pane" className="flex min-w-0 flex-col gap-3">
    {error != null && <ErrorBar error={error} onRetry={onRetry} retrying={loading} />}
    {!runs && loading && <DelayedSkeleton><div role="status" aria-busy="true" data-testid="runs-skeleton" className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-10 w-full" />)}</div></DelayedSkeleton>}
    {runs && runs.length === 0 && <div data-testid="runs-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("还没有运行记录。")} description={t("任务运行之后，每一次的结果会按时间排在这里。")} /></div>}
    {runs && runs.length > 0 && <RunsTimeline runs={runs} label={t("最近 20 次运行")} />}
  </div>;
}
