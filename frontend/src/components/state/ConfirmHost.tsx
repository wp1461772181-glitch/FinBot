import { Suspense, lazy, useEffect, useSyncExternalStore } from "react";
import { confirmQueue } from "./confirm";

// The dialog (Radix AlertDialog and the hold button) is fetched the first time something asks.
const ConfirmDialog = lazy(() => import("./ConfirmDialog"));

/** Mounted once in the shell: it lets `confirm()` ask (with no host, an ask is cancelled) and shows the ask at the front of the queue. */
export function ConfirmHost() {
  useEffect(() => { confirmQueue.attachHost(true); return () => confirmQueue.attachHost(false); }, []);
  const ask = useSyncExternalStore(confirmQueue.subscribe, confirmQueue.getSnapshot, confirmQueue.getSnapshot);
  return ask ? <Suspense fallback={null}><ConfirmDialog key={ask.id} ask={ask} /></Suspense> : null;
}
