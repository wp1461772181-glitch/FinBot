import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { Timeline } from "@/components/Timeline";
import type { MaterialAnalysisVersion } from "../../../types";
import { useLocale } from "../../../i18n";
import { formatDate } from "./AnalysisView";

export type Load<T> = { kind: "idle" } | { kind: "loading" } | { kind: "ready"; value: T } | { kind: "error"; message: string };

/** 分析历史: every saved analysis of the material, one line each with its version, model and time; the one on view is marked, pressing another opens it. */
export function HistoryView({ state, selectedAnalysisId, onSelect }: { state: Load<MaterialAnalysisVersion[]>; selectedAnalysisId: string | null; onSelect: (id: string) => void }) {
  const { locale, t } = useLocale();
  if (state.kind === "loading" || state.kind === "idle") return <DelayedSkeleton><SkeletonRows rows={3} /></DelayedSkeleton>;
  if (state.kind === "error") return <ErrorBar message={state.message} />;
  if (state.value.length === 0) return <EmptyState title={t("还没有保存成功的分析版本。失败的尝试只记录在最近任务状态中。")} className="rounded-md border border-dashed border-line" />;
  return <div data-testid="history-view">
    <Timeline label={t("分析历史")} selectedId={selectedAnalysisId} onSelect={onSelect}
      items={state.value.map(version => ({ id: version.analysis_id, title: `${t("分析")} v${version.version_no}`, meta: `${formatDate(version.created_at, locale)} · ${version.actual_model}`, marks: version.analysis_id === selectedAnalysisId ? <StatusBadge kind="neutral" className="h-5">{t("正在查看")}</StatusBadge> : null }))} />
  </div>;
}
