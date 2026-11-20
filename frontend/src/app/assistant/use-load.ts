import { useCallback, useEffect, useRef, useState } from "react";

export type Load<T> = { data: T | null; error: unknown; loading: boolean; reload: () => Promise<void> };

/**
 * One read as an assistant page holds it: `data` stays on screen while it is read again (after a write, or 重试), a read that fails leaves the last good
 * `data` with the `error` beside it, and `reload` never rejects.  A read that is superseded is aborted, so a slow old answer never lands over a newer one.
 */
export function useLoad<T>(read: (signal: AbortSignal) => Promise<T>, key = ""): Load<T> {
  const [state, setState] = useState<{ data: T | null; error: unknown; loading: boolean }>({ data: null, error: null, loading: true });
  const controller = useRef<AbortController | null>(null);
  const latest = useRef(read);
  latest.current = read;
  const reload = useCallback(async () => {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine;
    setState(previous => ({ ...previous, loading: true }));
    try {
      const data = await latest.current(mine.signal);
      if (!mine.signal.aborted) setState({ data, error: null, loading: false });
    } catch (error) {
      if (!mine.signal.aborted) setState(previous => ({ ...previous, error, loading: false }));
    }
  }, []);
  useEffect(() => {
    void reload();
    return () => controller.current?.abort();
  }, [reload, key]);
  return { ...state, reload };
}
