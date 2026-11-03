// Bloub avatar director: which engine state the main chat avatar shows, from what is happening (a turn running,
// something unread, a hover or click, nothing for a while). A clockless state machine: every call carries `now`
// (seconds), so node --test drives it with explicit times. React only forwards events and reads the result.
//
// The view also carries `expression`: CALM on every idle/notify/reaction/sleep base, the work-phase sequence (bloub-mood)
// while the body is in a work state. The face is a layer on top of the state, never a replacement for it.
//
// Priority, high to low:  work (turn lifecycle + its stingers)  >  notify (unread)  >  reaction (hover / click)  >
// life (sleep after a long idle)  >  idle.  Reactions never interrupt work; work pre-empts a reaction in progress.

import { CALM, MOOD_MORPH, moodAt } from "./bloub-mood.mjs";

/** Durations in seconds. DWELL is the engine's longest state morph (orbit, 0.6): the engine keeps ONE previous state,
 * so leaving a state sooner than that makes the fade jump instead of blend (bloub's MIN_BLOCK rule). */
export const T = {
  ATTENTION: 0.9,   // "noticed you" beat after a message is sent
  SUCCESS: 1.4,     // happy beat after an answer
  ERROR: 2.0,       // alert is cut before its "!" returns under 2 s (bloub states.ts minDuration)
  HOVER: 1.2,       // hover reaction holds this long at most, even if the pointer stays
  CLICK: 2.4,       // burst / comet are cut under 2.4 s (bloub minDuration)
  SLEEP_AFTER: 60,  // no interaction for this long -> sleep
  DWELL: 0.6,
  INTRO: 1.8        // arrival gaze turn (1.5) + a settle beat, same shape as bloub's INTRO montage
};

/** Event -> engine state. Ids are bloub's StateId. */
export const S = {
  attention: "wide", waiting: "orbit", tool: "orbit", answer: "thinking",
  success: "wink", error: "alert", hover: "wide", click: ["burst", "comet"],
  sleep: "sleep", notify: "notify", idle: "idle"
};

export function createDirector({ now = 0, reducedMotion = false } = {}) {
  const m = {
    reduced: reducedMotion, lastActivity: now,
    turn: null, stinger: null, unread: false,
    hover: { on: false, since: 0, used: false }, click: null, clicks: 0,
    introUntil: -Infinity,
    held: { state: S.idle, layer: "idle", changedAt: -Infinity }
  };

  function desired(t) {
    if (m.turn) {
      const attending = !m.reduced && !m.turn.quiet && t < m.turn.since + T.ATTENTION;
      return { state: attending ? S.attention : S[m.turn.phase], layer: "work" };
    }
    if (m.stinger && t < m.stinger.until) return { state: m.stinger.state, layer: "work" };
    if (m.unread) return { state: S.notify, layer: "notify" };
    if (!m.reduced) {
      if (m.click && t < m.click.until) return { state: m.click.state, layer: "reaction" };
      if (m.hover.on && !m.hover.used && t < m.hover.since + T.HOVER) return { state: S.hover, layer: "reaction" };
      if (t - m.lastActivity >= T.SLEEP_AFTER) return { state: S.sleep, layer: "life" };
    }
    return { state: S.idle, layer: "idle" };
  }

  return {
    send(event, t) {
      if (event.type !== "unread") m.lastActivity = t;
      switch (event.type) {
        case "turn-start":
          m.turn = { phase: "waiting", since: t, phaseSince: t, quiet: Boolean(event.quiet) };
          m.stinger = null; m.click = null;
          break;
        case "phase":
          if (m.turn && S[event.phase] && m.turn.phase !== event.phase) { m.turn.phase = event.phase; m.turn.phaseSince = t; }
          break;
        case "turn-end": {
          const was = m.turn; m.turn = null;
          if (!was) break;
          if (event.outcome === "done") m.stinger = { state: S.success, until: t + T.SUCCESS };
          else if (event.outcome === "error") m.stinger = { state: S.error, until: t + T.ERROR };
          else m.stinger = null;
          break;
        }
        case "unread": m.unread = Boolean(event.value); break;
        case "hover":
          m.hover = event.value ? { on: true, since: t, used: false } : { on: false, since: 0, used: false };
          break;
        case "click":
          m.click = { state: S.click[m.clicks++ % S.click.length], until: t + T.CLICK };
          m.hover.used = true;
          break;
        case "arrive": if (!m.reduced) m.introUntil = t + T.INTRO; break;
        default: break; // "activity": only the lastActivity touch above
      }
    },
    /** Resolve what to show at `now`. Reads must use a non-decreasing clock. */
    read(t) {
      const want = desired(t);
      // Morph floor: a state just entered is kept for DWELL, whatever outranks it.
      if (want.state !== m.held.state && t - m.held.changedAt < T.DWELL) {
        return view(m.held.state, m.held.layer, t);
      }
      if (want.state !== m.held.state) m.held = { state: want.state, layer: want.layer, changedAt: t };
      else m.held.layer = want.layer;
      return view(m.held.state, m.held.layer, t);
    }
  };

  function view(state, layer, t) {
    const idle = state === S.idle;
    // The face layer rides on the work body only (orbit / thinking); every other base is calm.
    const working = !m.reduced && m.turn && layer === "work" && (state === S.waiting || state === S.answer);
    const expression = working ? moodAt(m.turn.phase, t - m.turn.phaseSince) : CALM;
    return { state, layer, follow: !m.reduced && idle, intro: idle && t < m.introUntil, expression, moodMorph: MOOD_MORPH };
  }
}

/** First visit to a bot's chat in this page session plays the arrival; later visits don't. Reduced motion never consumes it. */
export function shouldArrive(seen, botId, reducedMotion) {
  if (!botId || reducedMotion || seen.has(botId)) return false;
  seen.add(botId);
  return true;
}

/** Where the running turn is, read off the streaming transcript: waiting / tool / answer (null when no turn runs). */
export function turnPhase(chatState, messages) {
  if (chatState !== "sending") return null;
  const last = messages?.[messages.length - 1];
  if (!last || last.role !== "assistant") return "waiting";
  const tools = last.tool_trace ?? [];
  if (tools.some(x => x.status === "running")) return "tool";
  if (String(last.content ?? "").trim()) return "answer";
  return tools.length ? "tool" : "waiting";
}

/** Chat state change -> director event (or null). The outcome of a finished turn is read off its last message. */
export function turnTransition(prev, next, messages) {
  if (prev !== "sending" && next === "sending") return { type: "turn-start" };
  if (prev === "sending" && next !== "sending") {
    if (next === "error") return { type: "turn-end", outcome: "error" };
    const last = messages?.[messages.length - 1];
    if (!last || last.role !== "assistant" || last.status === "cancelled") return { type: "turn-end", outcome: "cancel" };
    return { type: "turn-end", outcome: last.status === "failed" ? "error" : "done" };
  }
  return null;
}
