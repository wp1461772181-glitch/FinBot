import { useCallback, useEffect, useRef, useState } from "react";

type Page<T> = { items: T[]; next_before: string | null };
type State<T, P> = { items: T[]; next: string | null; loading: boolean; more: boolean; error: unknown; moreError: unknown; extra: P | null };

/**
 * A list read page by page with the server's `before` cursor.  A new `key` (the filters changed) starts again from the first page and aborts the read in flight;
 * `loadMore` appends the next page and keeps what is on screen when it fails.  `first` is the last first-page answer (the answers list reads its slow threshold from it).
 */
export function usePaged<T, P extends Page<T>>(read: (before: string | null, signal: AbortSignal) => Promise<P>, key: string) {
  const [state, setState] = useState<State<T, P>>({ items: [], next: null, loading: true, more: false, error: null, moreError: null, extra: null });
  const latest = useRef(read);
  latest.current = read;
  const controller = useRef<AbortController | null>(null);
  const next = useRef<string | null>(null);
  const busy = useRef(false);

  const start = useCallback(async () => {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine;
    busy.current = true;
    next.current = null;
    setState(previous => ({ ...previous, items: [], next: null, extra: null, loading: true, more: false, error: null, moreError: null }));   // the rows of the old filter go at once: never shown under the new one
    try {
      const page = await latest.current(null, mine.signal);
      if (mine.signal.aborted) return;
      next.current = page.next_before;
      setState({ items: page.items, next: page.next_before, loading: false, more: false, error: null, moreError: null, extra: page });
    } catch (error) {
      if (!mine.signal.aborted) setState(previous => ({ ...previous, loading: false, error }));
    } finally {
      if (controller.current === mine) busy.current = false;
    }
  }, []);

  useEffect(() => {
    void start();
    return () => controller.current?.abort();
  }, [start, key]);

  const loadMore = useCallback(async () => {
    const cursor = next.current;
    if (!cursor || busy.current) return;
    const mine = controller.current;
    if (!mine) return;
    busy.current = true;
    setState(previous => ({ ...previous, more: true, moreError: null }));
    try {
      const page = await latest.current(cursor, mine.signal);
      if (mine.signal.aborted) return;
      next.current = page.next_before;
      setState(previous => ({ ...previous, items: [...previous.items, ...page.items], next: page.next_before, more: false }));
    } catch (error) {
      if (!mine.signal.aborted) setState(previous => ({ ...previous, more: false, moreError: error }));
    } finally {
      if (controller.current === mine) busy.current = false;
    }
  }, []);

  return { ...state, reload: start, loadMore };
}
