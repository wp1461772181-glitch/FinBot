import { useCallback, useEffect, useRef, useState } from "react";
import { getPortfolio, type PortfolioSummary } from "../../api/portfolio-ledger";
import { getEarningsJudgments, getV2Forecasts, type EarningsJudgment, type V2ForecastListRow } from "../../api/forecast-v2";

/**
 * The ledger as the page holds it: `data` stays on screen while it is read again (after a write, or 重试), and a read that fails leaves the last good
 * `data` with the `error` beside it, so a refresh that fails never blanks the page.  `reload` never rejects.
 */
export function usePortfolio() {
  const [state, setState] = useState<{ data: PortfolioSummary | null; error: unknown; loading: boolean }>({ data: null, error: null, loading: true });
  const controller = useRef<AbortController | null>(null);
  const reload = useCallback(async () => {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine;
    setState(previous => ({ ...previous, loading: true }));
    try {
      const data = await getPortfolio(mine.signal);
      if (!mine.signal.aborted) setState({ data, error: null, loading: false });
    } catch (error) {
      if (!mine.signal.aborted) setState(previous => ({ ...previous, error, loading: false }));
    }
  }, []);
  useEffect(() => { void reload(); return () => controller.current?.abort(); }, [reload]);
  return { ...state, reload };
}

export type ResearchLists = { state: "loading" | "ready" | "partial" | "failed"; forecasts: V2ForecastListRow[]; judgments: EarningsJudgment[] };

/**
 * The two lists the 研究记录 lines are made from: one forecast list for every held symbol and one list of earnings judgments for the whole page, never one call
 * per position.  They are read once per set of held symbols (a write that does not change the set does not read them again).  A list that cannot be read leaves
 * what the other one gave; `state` says so, so the page can say it too.
 */
export function useResearchLists(symbols: string[]): ResearchLists {
  const [lists, setLists] = useState<ResearchLists>({ state: "loading", forecasts: [], judgments: [] });
  const key = symbols.slice(0, 30).join(",");
  useEffect(() => {
    if (!key) { setLists({ state: "ready", forecasts: [], judgments: [] }); return; }
    const mine = new AbortController();
    setLists(previous => ({ ...previous, state: "loading" }));
    Promise.allSettled([
      getV2Forecasts({ symbols: key.split(","), state: "open", limit: 200 }, mine.signal),
      getEarningsJudgments({ limit: 200 }, mine.signal),
    ]).then(([forecasts, judgments]) => {
      if (mine.signal.aborted) return;
      const failed = Number(forecasts.status === "rejected") + Number(judgments.status === "rejected");
      setLists({
        state: failed === 0 ? "ready" : failed === 2 ? "failed" : "partial",
        forecasts: forecasts.status === "fulfilled" ? forecasts.value.forecasts : [],
        judgments: judgments.status === "fulfilled" ? judgments.value : [],
      });
    });
    return () => mine.abort();
  }, [key]);
  return lists;
}
