import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { getV2ForecastRoots } from "../../api";
import { translatePhrase } from "../../i18n";
import { paths } from "../../routes.mjs";
import { useCompanyParam } from "./frames";

/**
 * /research/c/:symbol/latest?section=versions — the address the old #revisions turns into: the company's newest
 * forecast, opened on its version list.  It looks the forecast up, then replaces itself with the forecast's own
 * address; a company with no forecast goes to the forecast home, as #revisions always did.
 */
export function LatestRoute() {
  const navigate = useNavigate();
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
  return <main className="workspace">    {state.kind === "loading"
      ? <p role="status">{translatePhrase("正在读取…")}</p>
      : <p className="v2-notice error" role="alert">{translatePhrase("暂时无法读取预测日期列表。")} <button className="text-button" type="button" onClick={() => navigate(paths.forecasts())}>{translatePhrase("回到预测首页")}</button></p>}
  </main>;
}
