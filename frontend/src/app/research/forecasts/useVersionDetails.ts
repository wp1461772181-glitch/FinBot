import { useEffect, useRef, useState } from "react";
import { getV2ForecastVersion } from "../../../api/forecast-v2";
import type { V2TimelineEntry, V2VersionDetail } from "../../../types";

export type VersionDetails = {
  get: (id: string) => V2VersionDetail | undefined;
  all: Map<string, V2VersionDetail>;
  /** The selected version could not be read (the page says so and offers 重试). */
  failed: boolean;
  retry: () => void;
};

/**
 * The saved records of a forecast's versions.  The selected version and its parent are read first (what the page shows and compares); the others follow, three
 * at a time, so the version rail can mark which version changed its model.  A record is read once per page visit; a new chain (another forecast, or a
 * reload after a job) starts again.
 */
export function useVersionDetails(versions: V2TimelineEntry[], selectedId: string, chain: string): VersionDetails {
  const cache = useRef<{ chain: string; map: Map<string, V2VersionDetail>; flying: Set<string> }>({ chain, map: new Map(), flying: new Set() });
  const [, bump] = useState(0);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);
  if (cache.current.chain !== chain) cache.current = { chain, map: new Map(), flying: new Set() };
  const parentOf = versions.find(version => version.id === selectedId)?.parent_version_id ?? null;
  const known = new Set(versions.map(version => version.id));
  const order = [selectedId, parentOf, ...[...versions].reverse().map(version => version.id)].filter((id, index, list): id is string => Boolean(id) && list.indexOf(id) === index && known.has(id as string));
  const key = order.join(",");

  useEffect(() => {
    if (!order.length) return;
    const controller = new AbortController();
    const state = cache.current;
    setFailed(false);
    const load = async (id: string) => {
      if (state.map.has(id) || state.flying.has(id)) return;
      state.flying.add(id);
      try {
        const detail = await getV2ForecastVersion(id, controller.signal);
        if (!controller.signal.aborted && cache.current === state) { state.map.set(id, detail); bump(value => value + 1); }
      } catch {
        if (!controller.signal.aborted && id === order[0]) setFailed(true);
      } finally { state.flying.delete(id); }
    };
    void (async () => {
      await Promise.all(order.slice(0, 2).map(load));
      const rest = order.slice(2);
      for (let at = 0; at < rest.length && !controller.signal.aborted; at += 3) await Promise.all(rest.slice(at, at + 3).map(load));
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, chain, tick]);

  return { get: id => cache.current.map.get(id), all: cache.current.map, failed, retry: () => setTick(value => value + 1) };
}
