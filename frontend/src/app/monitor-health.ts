import { useSyncExternalStore } from "react";

// What the shell knows of the automatic monitor, as the dot beside 研究: "action" (late), "failure" (failing) or null (well, no record, or not read yet).  This file is on the first
// screen, so it holds only that value; the rule that makes it from the monitor's health (monitor-dot.mjs) lives with the readers (`readMonitorStatus`), which every read of the
// monitor status (the research area's own, the page's, the chips') goes through.
let dot: "action" | "failure" | null = null;
const listeners = new Set<() => void>();

export function setMonitorDot(next: typeof dot) {
  if (next !== dot) { dot = next; listeners.forEach(listener => listener()); }
}

export const useMonitorDot = () => useSyncExternalStore(notify => { listeners.add(notify); return () => { listeners.delete(notify); }; }, () => dot);
