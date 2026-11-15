import { useEffect, useState } from "react";
import { listInbox, listTaskProposals } from "../../api/inbox";
import { routinesBadge } from "../../inbox-items.mjs";

/**
 * The one to-do number of the app (design 3.1: the 任务 entry carries it, bot rows do not): the routine cards bots
 * proposed that still wait for a press, plus the writes unattended runs suggested.  Two existing endpoints, added up
 * (design 7.4, constraint 3); the same two lists the 任务 page shows.  It is read when the owner opens the app, again
 * whenever `refreshKey` changes (the bot list reloads after every action on the 任务 page and every finished answer)
 * and when the tab comes back to the front.  A list that cannot be read counts for nothing; the number just stays low.
 */
export function useRoutinesBadge(enabled: boolean, refreshKey: unknown): number {
  const [count, setCount] = useState(0);
  const [visibleTick, setVisibleTick] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const onVisible = () => { if (document.visibilityState === "visible") setVisibleTick(tick => tick + 1); };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [enabled]);
  useEffect(() => {
    if (!enabled) { setCount(0); return; }
    const controller = new AbortController();
    void Promise.allSettled([listTaskProposals(controller.signal), listInbox("confirm", controller.signal)]).then(([proposals, confirms]) => {
      if (controller.signal.aborted) return;
      setCount(routinesBadge(proposals.status === "fulfilled" ? proposals.value : [], confirms.status === "fulfilled" ? confirms.value : []));
    });
    return () => controller.abort();
  }, [enabled, refreshKey, visibleTick]);
  return count;
}
