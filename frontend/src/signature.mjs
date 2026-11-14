// The bot's signature on the chat line (design 6.6): which trace of thinking and which caret a persona gets, how a finished turn
// draws its closing line, and the period rule.  Pure (no DOM, no React): node --test covers it.  The shapes themselves are CSS
// (src/styles/bots-signature.css, selected by data-archetype / data-aura-variant on the chat page); this file is the single table
// that says which is which, so the sample page, the smoke checks and the tests read the same answer.
import { awaitsUser } from "./chat-clarification.mjs";

/** The six traces of thinking (the process bar's first cell), by name.  Each is one `@keyframes` family in bots-signature.css. */
export const TRACES = ["candles", "streaks", "steps", "arc", "lines", "drift", "orbit"];

/** The five carets.  The lead and the generalist share the plain bar (the design lists five). */
export const CURSORS = ["bar", "slant", "underline", "hairline", "bar-block"];

/**
 * Persona -> { trace, cursor }.  The tracker's variant decides: speed-lines (the quick one) streaks, halo (the calm one) arc.  The standard
 * tracker (reticle) keeps its family's slanted caret and a drift: the same three short lines as the quick one's streaks, at a constant
 * speed and evenly spaced, so it reads as that bot's even-tempered sibling.
 */
export function signatureOf(persona) {
  const archetype = persona?.archetype, variant = persona?.auraVariant;
  if (archetype === "lead") return { trace: "candles", cursor: "bar" };
  if (archetype === "sentinel") return { trace: "steps", cursor: "underline" };
  if (archetype === "reader") return { trace: "lines", cursor: "bar-block" };
  if (archetype === "tracker") {
    if (variant === "speed-lines") return { trace: "streaks", cursor: "slant" };
    if (variant === "halo") return { trace: "arc", cursor: "hairline" };
    return { trace: "drift", cursor: "slant" };
  }
  return { trace: "orbit", cursor: "bar" };
}

/** The base period of the trace's loop (design 6.6: 1.2 s) and of the caret's blink, seconds. */
export const TRACE_PERIOD_S = 1.2;
export const CARET_PERIOD_S = 1;

/**
 * A loop's period for a bot: the base DIVIDED by its tempo (tempo is a speed multiplier, 0.8 to 1.25: the quick bot's loop is shorter,
 * the calm one's longer).  A tempo that is not a usable number leaves the base.
 */
export function periodFor(baseSeconds, tempo) {
  const t = typeof tempo === "number" && Number.isFinite(tempo) && tempo > 0 ? tempo : 1;
  return baseSeconds / t;
}

/**
 * How the turn that has just stopped ended, read the way the avatar's director reads it (bloub-director.turnTransition, same order of
 * precedence), without the director: error > cancel > waiting > partial > done.  null when no turn has just stopped (a state change that
 * is not "sending" -> something else).  `messages` is the transcript at that moment.
 */
export function turnEndOutcome(prevState, nextState, messages) {
  if (prevState !== "sending" || nextState === "sending") return null;
  if (nextState === "error") return "error";
  const last = Array.isArray(messages) && messages.length ? messages[messages.length - 1] : undefined;
  if (last && last.role === "assistant" && last.status === "failed") return "error";
  if (!last || last.role !== "assistant" || last.status === "cancelled") return "cancel";
  if (awaitsUser(last)) return "waiting";
  return last.status === "partially_succeeded" ? "partial" : "done";
}

const ENDED_OK = new Set(["complete", "succeeded", "partially_succeeded"]);

/**
 * The line under an assistant message: "plain" (1px neutral), "done" / "partial" (1px neutral with the 2px signature sweep over it,
 * once), "failed" (1px danger, still), or null (no line: a turn that was stopped, one still running, one with nothing to close).
 * `ended` is the outcome of the turn this very tab has just seen end for THIS message (turnEndOutcome), or null for every message that
 * was already there (history, another tab's turn): those are only ever plain.
 */
export function doneLineState(message, { streaming = false, ended = null } = {}) {
  if (!message || message.role !== "assistant" || streaming) return null;
  if (message.status === "failed") return "failed";
  if (!message.content) return null;
  if (message.status && !ENDED_OK.has(message.status)) return null;
  if (ended === "done") return "done";
  if (ended === "partial") return "partial";
  return "plain";
}
