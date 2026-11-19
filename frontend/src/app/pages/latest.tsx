import { useEffect, useState } from "react";
import { Navigate } from "react-router";
import { EmptyState } from "@/components/state/EmptyState";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { getV2ForecastRoots } from "../../api/forecast-v2";
import { translatePhrase } from "../../i18n";
import { paths } from "../../routes.mjs";
import { useCompanyParam } from "./frames";

/**
 * /research/c/:symbol/latest?section=versions — the address the old #revisions turns into: the company's newest
 * forecast, opened on its version list.  It looks the forecast up, then replaces itself with the forecast's own
 * address; a company with no forecast goes to the forecast home, as #revisions always did.
 */
export function LatestRoute() {
  const symbol = useCompanyParam();
  const [state, setState] = useState<{ kind: "loading" } | { kind: "ready"; rootId: string | null } | { kind: "error" }>({ kind: "loading" });
  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    setState({ kind: "loading" });
    getV2ForecastRoots(symbol, controller.signal)
      .then((roots) => { if (!controller.signal.aborted) setState({ kind: "ready", rootId: roots.roots[0]?.id ?? null }); })
      .catch(() => { if (!controller.signal.aborted) setState({ kind: "error" }); });
    return () => controller.abort();
  }, [symbol]);
  if (!symbol) return <Navigate to={paths.forecasts()} replace />;
  if (state.kind === "ready") return <Navigate to={state.rootId ? paths.forecast(state.rootId, { section: "versions" }) : paths.forecasts()} replace />;
  // The two short-lived states: a skeleton while the list is read, and, when the read fails, the same sentence and way out as before.
  return <main data-testid="latest-redirect" className="mx-auto flex w-full max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6">
    {state.kind === "loading"
      ? <DelayedSkeleton><SkeletonRows rows={3} /></DelayedSkeleton>
      : <div role="alert" data-testid="latest-error"><EmptyState title={translatePhrase("暂时无法读取预测日期列表。")} action={{ label: translatePhrase("回到预测首页"), to: paths.forecasts() }} /></div>}
  </main>;
}
