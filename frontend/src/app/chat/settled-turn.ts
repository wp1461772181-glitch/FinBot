// Which message's turn this tab has just seen end, and how (the closing line's trigger, design 6.6).  Read off the session's own state
// change (sending -> ready / idle / error) and the transcript at that moment; nothing is asked of the avatar, which is a lazy chunk the line
// must not wait for.  History, another tab's turn and a conversation opened later never set it, so they only ever get the plain hairline.
import { useLayoutEffect, useRef, useState } from "react";
import { turnEndOutcome, type TurnEnd } from "../../signature.mjs";

export type SettledTurn = { index: number; outcome: TurnEnd };

export function useSettledTurn(state: string, messages: ReadonlyArray<{ role?: string; status?: string; clarification?: unknown }>): SettledTurn | null {
  const [settled, setSettled] = useState<SettledTurn | null>(null);
  const prev = useRef(state);
  // Layout effect: the line is drawn with its sweep in the same frame the turn is over, not a frame later.
  useLayoutEffect(() => {
    const before = prev.current;
    prev.current = state;
    if (state === "sending") { if (before !== "sending") setSettled(null); return; }
    // A turn ends in "ready" (a signed-in line), "idle" (a guest's) or "error"; "restoring" / "testing" are the line being swapped, not a turn ending.
    if (state !== "ready" && state !== "idle" && state !== "error") return;
    const outcome = turnEndOutcome(before, state, messages);
    if (outcome) setSettled({ index: messages.length - 1, outcome });
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps
  return settled;
}
