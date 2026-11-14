/**
 * Bring the card that is waiting for an answer into view and put the focus on its main action (a revision card whose button still waits for ticks:
 * its first tick).  The card is a chunk of its own and may still be on its way, so this looks for it for a moment before giving up.
 * Returns a promise of whether a card was found.
 */
export function focusWaitingCard(): Promise<boolean> {
  const find = () => document.querySelector<HTMLElement>('[data-slot="approval-card"][data-state="active"]');
  const reach = (card: HTMLElement) => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
    const target = card.querySelector<HTMLElement>("[data-approval-primary]:not(:disabled)")
      ?? card.querySelector<HTMLElement>("[data-approval-option]:not(:disabled)")
      ?? card.querySelector<HTMLElement>("button:not(:disabled), input:not(:disabled)");
    target?.focus({ preventScroll: true });
  };
  return new Promise((resolve) => {
    const started = Date.now();
    const look = () => {
      const card = find();
      if (card) { reach(card); resolve(true); return; }
      if (Date.now() - started > 3000) { resolve(false); return; }
      window.setTimeout(look, 100);
    };
    look();
  });
}
