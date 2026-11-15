// How the new thread comes in after a switch (design 6.7): the last three messages fade in 20 ms apart (a desktop), the whole line slides 24px sideways (a
// phone), or the line cross-fades over 150 ms (reduced motion); and a bot that waits for you opens its line at the card.  A chunk of its own, fetched shortly
// after the first paint (handoff-intent.ts): the first screen only asks whether it has arrived (a switch in the first half second has no entrance).
import { lineMotion, staggerDelay, type LineMotion } from "../../handoff-line.mjs";
import { getMotion, motionOff } from "../../motion-store.mjs";
import { beginHandoff, type Intent } from "./handoff-intent";

export interface Entry { motion: LineMotion; dir: number; delay: (index: number) => number | undefined }

/** The entrance of a thread that holds `count` messages, for the switch `intent` (the thread was mounted on the line that belongs to the bot). */
export function entryOf(intent: Intent, count: number, phone: boolean): Entry {
  const motion = lineMotion({ level: getMotion().level, phone });
  return { motion, dir: intent.dir || 1, delay: index => (motion === "rise" && index < count ? staggerDelay(index, count) ?? undefined : undefined) };
}

/** The card that waits for an answer, brought into view and nothing more: no focus moves (the focus is the composer's or the reader's). */
export function revealWaitingCard(): Promise<boolean> {
  return new Promise((resolve) => {
    const started = Date.now();
    const look = () => {
      const card = document.querySelector<HTMLElement>('[data-slot="approval-card"][data-state="active"]');
      if (card) {
        card.scrollIntoView({ block: "center", behavior: motionOff() ? "auto" : "smooth" });
        resolve(true);
      } else if (Date.now() - started > 3000) resolve(false);
      else window.setTimeout(look, 100);
    };
    look();
  });
}

// A switch by address (the back button, a link in an answer, the command palette): there is no click to hear, but the hash change comes before the
// new line renders, which is nearly as early.  (Heard from the moment this chunk has arrived, shortly after the first paint.)
if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => {
    const match = /^#\/chat\/([^/]+)(?:\/settings)?$/.exec(window.location.hash);
    const id = match?.[1] ? decodeURIComponent(match[1]) : null;
    if (id && id !== "history" && id !== "c") beginHandoff({ to: id, source: "route" });
  });
}
