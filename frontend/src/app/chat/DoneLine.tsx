import type { DoneLine as DoneLineState } from "../../signature.mjs";

/**
 * The line under a finished answer (design 6.6).  A hairline (1px, neutral) once the turn is over; for the turn this tab has just seen end,
 * a 2px stroke in the bot's signature colour is drawn over it from left to right once (320ms) and then goes, which leaves the hairline.
 * A partial answer's stroke stops three quarters of the way.  A failed turn's line is the danger colour and does not move.  Colour only
 * differs between bots; the CSS is in styles/bots-signature.css (transform and opacity only, off with reduced motion).
 */
export function DoneLine({ state }: { state: DoneLineState }) {
  return <div data-testid="done-line" data-state={state} aria-hidden="true" className="done-line">
    {(state === "done" || state === "partial") && <span data-slot="done-sweep" className="done-sweep" />}
  </div>;
}
