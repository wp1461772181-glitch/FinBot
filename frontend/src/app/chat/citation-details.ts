import { useCallback, useEffect, useSyncExternalStore } from "react";
import { getKnowledgeCitation, type KnowledgeCitationDetail } from "../../api";

// The excerpt of a citation held in the knowledge store is fetched once (the same request the old drawer made on click) and shared by
// everything that shows it: the hover preview on a chip and the card in the 来源 tab.

export type DetailState = { status: "loading" } | { status: "ready"; value: KnowledgeCitationDetail } | { status: "failed"; error: unknown };

const entries = new Map<string, DetailState>();
const listeners = new Set<() => void>();
const publish = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };

/** Ask for a citation's detail unless it is already here or on the way (`force` asks again after a failure). */
export function loadCitationDetail(chunkId: string, force = false): void {
  const current = entries.get(chunkId);
  if (current && !(force && current.status === "failed")) return;
  entries.set(chunkId, { status: "loading" });
  publish();
  getKnowledgeCitation(chunkId).then(
    (value) => { entries.set(chunkId, { status: "ready", value }); publish(); },
    (error) => { entries.set(chunkId, { status: "failed", error }); publish(); },
  );
}

/** The detail of a chunk, and a way to ask again.  `load: true` starts the request when the component mounts. */
export function useCitationDetail(chunkId: string | null | undefined, load: boolean): { detail: DetailState | undefined; reload: () => void } {
  const detail = useSyncExternalStore(subscribe, () => (chunkId ? entries.get(chunkId) : undefined), () => undefined);
  useEffect(() => { if (load && chunkId) loadCitationDetail(chunkId); }, [chunkId, load]);
  const reload = useCallback(() => { if (chunkId) loadCitationDetail(chunkId, true); }, [chunkId]);
  return { detail, reload };
}
