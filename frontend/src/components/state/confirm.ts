import { createConfirmQueue, type ConfirmOptions } from "../../confirm-queue.mjs";

export type { ConfirmOptions };
export const confirmQueue = createConfirmQueue();

/**
 * Ask the reader to confirm, in the app (design 4.0, 破坏性确认) rather than the browser's own box: `if (!(await confirm({ ... }))) return;`.
 * True when they confirmed, false when they cancelled, pressed Esc or clicked away.  Say what will happen (`description`);
 * for what cannot be undone, `hold: true` makes the confirm button press-and-hold.  Focus goes back to where it was.
 */
export function confirm(options: ConfirmOptions): Promise<boolean> {
  const active = typeof document !== "undefined" && document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
  return confirmQueue.ask({ returnFocus: active, ...options });
}
