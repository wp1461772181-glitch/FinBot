import { useEffect, useId, useReducer, useRef, useState, type KeyboardEvent } from "react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useLocale } from "../../i18n";
import { initialHold, stepHold, HOLD_MS, type HoldEvent, type HoldState } from "../../hold-confirm.mjs";

const reduce = (state: HoldState, event: HoldEvent & { reducedMotion: boolean }): HoldState => stepHold(state, event, { reducedMotion: event.reducedMotion });

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const update = () => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/**
 * Press and hold to confirm (design 5.4: for what cannot be undone).  Hold the button about a second, with a fill that shows how
 * far it is; letting go early starts over.  By keyboard: hold Space or Enter.  Two ways round it, for readers who cannot or do not
 * want to hold, each giving the same confirmation: with reduced motion (no fill to watch) and for a click that came with no press
 * before it (a screen reader's activate, voice control), it is press twice.  The state machine is hold-confirm.mjs.
 */
export function HoldButton({ label, danger = true, onConfirmed }: { label: string; danger?: boolean; onConfirmed: () => void }) {
  const { t } = useLocale();
  const reducedMotion = usePrefersReducedMotion();
  const [state, dispatch] = useReducer(reduce, undefined, initialHold);
  const hintId = useId();
  const pressed = useRef(false);        // a pointer or key press began on this button: its click is part of that press
  const confirmed = useRef(false);
  const dispatchEvent = (event: HoldEvent) => dispatch({ ...event, reducedMotion });
  // The clock: a hold completes by time, an armed button disarms by time.
  useEffect(() => {
    if (state.phase !== "holding" && state.phase !== "armed") return;
    const timer = window.setInterval(() => dispatchEvent({ type: "tick", now: performance.now() }), 40);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase, reducedMotion]);
  useEffect(() => { if (state.phase === "done" && !confirmed.current) { confirmed.current = true; onConfirmed(); } }, [state.phase, onConfirmed]);

  const keyHold = (event: KeyboardEvent<HTMLButtonElement>) => event.key === " " || event.key === "Enter";
  const armed = state.phase === "armed";
  const holding = state.phase === "holding";
  const shown = armed ? t("再点一次确认") : label;
  const hint = reducedMotion ? t("点两次确认") : t("按住约 1 秒确认；键盘：按住空格或回车");
  // The same look as the dialog's ordinary confirm button (Button variants), so the two confirmations read as one family.
  const base = buttonVariants({ variant: danger ? "destructive" : "default" });
  return <>
    <button type="button" data-slot="hold-button" data-phase={state.phase} aria-describedby={hintId}
      className={cn(base, "relative min-w-24 select-none overflow-hidden touch-none")}
      onPointerDown={(event) => { if (event.button !== 0) return; pressed.current = true; dispatchEvent({ type: "press", via: "pointer", now: performance.now() }); }}
      onPointerUp={() => dispatchEvent({ type: "release" })}
      onPointerLeave={() => dispatchEvent({ type: "release" })}
      onPointerCancel={() => dispatchEvent({ type: "release" })}
      onKeyDown={(event) => { if (!keyHold(event)) return; event.preventDefault(); if (event.repeat) return; pressed.current = true; dispatchEvent({ type: "press", via: "key", now: performance.now() }); }}
      onKeyUp={(event) => { if (!keyHold(event)) return; event.preventDefault(); dispatchEvent({ type: "release" }); }}
      onBlur={() => dispatchEvent({ type: "blur" })}
      onContextMenu={(event) => event.preventDefault()}
      onClick={() => {
        // A click that follows a press was handled by the press; one that did not (assistive technology) is the two-step path.
        if (pressed.current) { pressed.current = false; return; }
        dispatchEvent({ type: "click", now: performance.now() });
      }}>
      <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 bg-black/25 dark:bg-white/25"
        style={{ width: holding && !reducedMotion ? "100%" : "0%", transition: holding && !reducedMotion ? `width ${HOLD_MS}ms linear` : "none" }} />
      <span className="relative">{shown}</span>
    </button>
    <p id={hintId} className="basis-full text-caption text-muted-foreground sm:order-first sm:basis-auto sm:flex-1 sm:text-left">{hint}</p>
    <span role="status" className="sr-only">{holding ? t("继续按住…") : armed ? t("再次激活以确认") : ""}</span>
  </>;
}
