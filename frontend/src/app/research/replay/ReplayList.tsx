import { StatusBadge } from "@/components/StatusBadge";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { cn } from "@/lib/utils";
import type { V2EvaluationVersion } from "../../../types";
import { useLocale } from "../../../i18n";
import { day } from "../forecasts/format";
import { directionPhrase, evaluationKind, evaluationPhrase } from "./replay-model.mjs";

export type ListState = { kind: "loading" } | { kind: "ready"; rows: V2EvaluationVersion[] } | { kind: "error"; message: string };

/** The replays of one company, newest decision day first: day, the version, and the state of its evaluation as a badge (with the real direction once it is known). */
export function ReplayList({ symbol, state, selectedId, onSelect, onRetry, onFillForm }: { symbol: string; state: ListState; selectedId: string; onSelect: (id: string) => void; onRetry: () => void; onFillForm: () => void }) {
  const { t, locale } = useLocale();
  const count = state.kind === "ready" ? state.rows.length : null;
  return <section data-testid="replay-list" aria-labelledby="replay-list-title" className="flex min-w-0 flex-col gap-3">
    <div className="flex items-baseline gap-3">
      <h2 id="replay-list-title" className="text-title-s text-ink"><span className="font-mono">{symbol}</span> · {t("回放样本")}</h2>
      {count !== null && <span data-testid="replay-count" className="text-caption text-muted-foreground">{locale === "en-US" ? `${count} ${count === 1 ? "replay" : "replays"}` : `${count} ${t("条")}`}</span>}
    </div>
    {state.kind === "loading" && <DelayedSkeleton><SkeletonRows rows={4} /></DelayedSkeleton>}
    {state.kind === "error" && <ErrorBar message={state.message} onRetry={onRetry} />}
    {state.kind === "ready" && (state.rows.length === 0
      ? <EmptyState title={t("还没有历史回放")} description={t("历史回放用当时可用的行情和材料重做一次预测，再和到期后的真实结果对照。提交上方表单后，回放会显示在这里，并在 20 个交易日目标到期后关联真实结果。")} action={{ label: t("去填写上面的表单"), onClick: onFillForm }} className="rounded-md border border-dashed border-line" />
      : <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {state.rows.map(row => {
          const status = row.latest_evaluation?.status ?? "pending";
          const selected = row.id === selectedId;
          return <li key={row.id}>
            <button type="button" data-testid="replay-row" data-id={row.id} data-selected={selected ? "" : undefined} aria-current={selected ? "true" : undefined} onClick={() => onSelect(row.id)}
              className={cn("flex w-full min-w-0 flex-col gap-1.5 rounded-md border px-3 py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11", selected ? "border-brand bg-brand-soft" : "border-line bg-surface hover:bg-sunken")}>
              <span className="flex min-w-0 items-baseline gap-2"><span className="font-mono text-small text-muted-foreground">{symbol}</span><strong className="text-body font-medium text-ink">{day(row.decision_at)}</strong></span>
              <span className="text-caption text-muted-foreground">{t("第")} {row.version_no} {t("版")} · {t(row.trigger_type === "historical_replay" ? "历史回放" : "历史研究")}</span>
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1"><StatusBadge kind={evaluationKind(status)} className="h-5">{t(evaluationPhrase(status))}</StatusBadge>{row.latest_evaluation?.actual_label && <span className="text-caption text-ink-2">{t(directionPhrase(row.latest_evaluation.actual_label))}</span>}</span>
            </button>
          </li>;
        })}
      </ul>)}
  </section>;
}
