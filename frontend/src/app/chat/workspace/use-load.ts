import { useEffect, useState } from "react";

export type Load<T> = { kind: "loading" } | { kind: "ready"; value: T } | { kind: "error" };

// The cards that read data which changes slowly (the price history, the filing list) keep their last answer for a minute, so switching the stock back and forth does not ask again.
const cache = new Map<string, { at: number; value: unknown }>();
const CACHE_MS = 60_000;

/**
 * One card's read: loading, then the answer or an error.  Each card has its own, so one failing read never blanks the others.  `cached` keeps the answer for 60 seconds under `key`.
 * This is the workspace's own hook (it carries the cache); the shared `useLoad` of src/app/use-load.ts (the assistant and settings pages) is a different one and is not merged with it.
 */
export function useLoad<T>(key: string, load: (signal: AbortSignal) => Promise<T>, cached = false): [Load<T>, () => void] {
  const [state, setState] = useState<Load<T>>({ kind: "loading" }), [tick, setTick] = useState(0);
  useEffect(() => {
    const hit = cached ? cache.get(key) : undefined;
    if (hit && Date.now() - hit.at < CACHE_MS && tick === 0) { setState({ kind: "ready", value: hit.value as T }); return; }
    const controller = new AbortController();
    setState({ kind: "loading" });
    load(controller.signal).then(value => { if (!controller.signal.aborted) { if (cached) cache.set(key, { at: Date.now(), value }); setState({ kind: "ready", value }); } })
      .catch(() => { if (!controller.signal.aborted) setState({ kind: "error" }); });
    return () => controller.abort();
  }, [key, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return [state, () => setTick(n => n + 1)];
}
