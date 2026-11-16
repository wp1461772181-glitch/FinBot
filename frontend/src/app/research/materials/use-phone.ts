import { useSyncExternalStore } from "react";

/** The phone layout (everything below the `lg` breakpoint).  Kept here, not imported from the chat page: sharing that module would make it a file of its own on the first screen. */
const PHONE_QUERY = "(max-width: 1023px)";

/** True while the window matches the phone query (re-read when it changes); false where matchMedia does not exist. */
export function usePhone(): boolean {
  return useSyncExternalStore(
    (notify) => { const list = window.matchMedia?.(PHONE_QUERY); list?.addEventListener?.("change", notify); return () => list?.removeEventListener?.("change", notify); },
    () => window.matchMedia?.(PHONE_QUERY).matches ?? false,
    () => false,
  );
}
