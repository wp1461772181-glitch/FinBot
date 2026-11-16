import { useEffect, useState } from "react";

/** One read of the backend: loading, its value, or the error it ended in. */
export type Read<T> = { kind: "loading" } | { kind: "ready"; value: T } | { kind: "error"; error: unknown };
const LOADING: Read<never> = { kind: "loading" };

/**
 * Read once per `key` (a new key starts a new read and drops the old answer; the old request is aborted).  `retry` reads again under the same key.
 * `enabled: false` waits.  Used by the research pages, where each block of a page loads and fails on its own.
 */
export function useRead<T>(key: string, load: (signal: AbortSignal) => Promise<T>, enabled = true): [Read<T>, () => void] {
  const [tick, setTick] = useState(0);
  const id = `${key}#${tick}`;
  const [state, setState] = useState<{ id: string; read: Read<T> }>({ id: "", read: LOADING });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    load(controller.signal)
      .then(value => { if (!controller.signal.aborted) setState({ id, read: { kind: "ready", value } }); })
      .catch(error => { if (!controller.signal.aborted) setState({ id, read: { kind: "error", error } }); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, enabled]);
  return [state.id === id ? state.read : LOADING, () => setTick(n => n + 1)];
}
