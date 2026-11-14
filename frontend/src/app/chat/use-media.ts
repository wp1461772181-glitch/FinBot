import { useSyncExternalStore } from "react";

/** The phone layout of the chat page (design 4.2): everything below the `lg` breakpoint. */
export const PHONE_QUERY = "(max-width: 1023px)";

/** True while the window matches the media query (re-read when it changes).  Always false where matchMedia does not exist. */
export function useMatchMedia(query: string): boolean {
  return useSyncExternalStore(
    (notify) => { const list = window.matchMedia?.(query); list?.addEventListener?.("change", notify); return () => list?.removeEventListener?.("change", notify); },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  );
}

export const usePhone = () => useMatchMedia(PHONE_QUERY);
