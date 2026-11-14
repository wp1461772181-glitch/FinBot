import { useSyncExternalStore } from "react";

/** Whether anything has asked for a toast yet.  The toaster (sonner) is fetched the first time one is; until then the app carries only this flag. */
let needed = false;
const listeners = new Set<() => void>();
export function needToaster() { if (!needed) { needed = true; for (const listener of [...listeners]) listener(); } }
export function useToasterNeeded() { return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => needed, () => false); }
