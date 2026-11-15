// Bloub avatar director: which engine state the main chat avatar shows, from what is happening (a turn running,
// something unread, a hover or click, nothing for a while). A clockless state machine: every call carries `now`
// (seconds), so node --test drives it with explicit times. React only forwards events and reads the result.
//
// The view also carries `expression`: CALM on every idle/notify/reaction/sleep base, the work-phase sequence (bloub-mood, one
// set per archetype) while a work pose is up. The face is a layer on top of the state, never a replacement for it.
//
// A turn can end five ways (see turnTransition): done / error / cancel / waiting / partial. Only done and error play a
// stinger. "waiting" (the ball is in the user's court) holds a pose of its own until you answer (or `waiting-clear`: the card ran
// out); "partial" (partially_succeeded) nods once: no state of its own, the renderer moves whatever body is shown (`view.nod`, 0..1).
// Both are exposed on the view for the renderer: `ended`, `waitingForUser`, `nod`.
//
// A1 adds the poses of design 6.3: listening (the composer has text), verify, waiting-for-you (an amber dot, a `wide` every
// 6 s, three times), offline (a frozen, half-grey idle) and the 10-second sleep freeze. The tool phase is no longer an orbit: the
// body is `idle` with the gaze turned to the side where the aura will sit (A2). Per-archetype tables live in `bodyTable`.
//
// Time constants (T.*) are the same for every bot: the skeleton of design 6.2 (done <= 1.4 s, failed <= 2.0 s, dwell 0.6 s). The
// persona's tempo is NOT applied here; the renderer multiplies the clock it feeds the engine (and this file scales the face rotation).
//
// A4 adds the handoff (design 6.7): the same director, the same body, becomes another bot.  `send({ type: "handoff", persona, at, quiet, unread })`
// resets what belonged to the line that is left (its turn, its stinger, its unread...), keeps the old persona for the exit (view.handoff.phase
// "leave", the old aura leaves), swaps to the new persona at SWAP, plays the swirl and the entrance (view.handoff "swap" / "enter" / "settle") and
// goes back to the new bot's rest at SWIRL_END.  `quiet` (the new bot is already working): no swirl, no entrance, the work pose at once.  A switch
// asked for while one is under way goes straight to the last target (the one in between is never shown: `carry` keeps the body's pose
// continuous).  Reduced motion: the persona is swapped at once and nothing plays.  `persona` swaps the persona silently (a late volatility).
//
// Priority, high to low:  work (turn lifecycle)  >  handoff (swirl)  >  its stingers, waiting-for-you  >  offline  >  glance at the unread
// divider  >  notify (unread)  >  listening  >  reaction (hover / click)  >  life (sleep after a long idle)  >  idle.  Reactions never interrupt work.

import { CALM, MOOD_MORPH, moodAt, MOODS_BY_ARCHETYPE } from "./bloub-mood.mjs";
import { awaitsUser } from "./chat-clarification.mjs";
import { turnSignal } from "./turn-signals.mjs";
import { T } from "./bloub-timing.mjs";
import { toolGaze } from "./aura/gaze.mjs";
import { handoffBody } from "./aura/handoff.mjs";
import { HANDOFF } from "./handoff.mjs";

export { T };

/** Event -> engine state. Ids are bloub's StateId. This is the default table; `bodyTable` derives each archetype's from it. */
export const S = {
  attention: "wide", waiting: "orbit", tool: "idle", verify: "idle", answer: "thinking", listen: "idle", hold: "idle",
  success: "wink", error: "alert", hover: "wide", click: ["burst", "comet"],
  sleep: "sleep", notify: "notify", idle: "idle"
};

/** How long a click reaction holds, by engine state (burst / comet are cut under 2.4 s; the short ones just play out). */
const CLICK_FOR = { burst: T.CLICK, comet: T.CLICK, exclaim: 1.8, wink: T.SUCCESS, wide: T.HOVER };

/** The default persona: the lead's. A director made without one behaves as it did before personalities existed. */
const NEUTRAL = { archetype: "lead", tempo: 1, easing: "smooth", restGaze: "follow", auraVariant: "ticks" };

/**
 * The state table of one personality: the default `S` with the click reactions of 6.5 (lead: burst / comet in turn; tracker fast:
 * comet; tracker calm: wink; any other tracker: burst / comet; sentinel: exclaim; reader: wide; generalist: burst / comet).
 * The bodies differ little by design (4 beats of grammar are shared); this is where A2 hangs the aura commands.
 */
export function bodyTable(persona = NEUTRAL) {
  const click = persona.archetype === "sentinel" ? ["exclaim"]
    : persona.archetype === "reader" ? ["wide"]
    : persona.archetype === "tracker" && persona.auraVariant === "speed-lines" ? ["comet"]
    : persona.archetype === "tracker" && persona.auraVariant === "halo" ? ["wink"]
    : S.click;
  return { ...S, click };
}

/** Which face sequence (bloub-mood phase) a pose wears; poses not listed rest on CALM. */
const MOOD_PHASE = { waiting: "waiting", tool: "tool", verify: "verify", answer: "answer", listen: "listen", hold: "hold" };

const WORK_PHASES = ["waiting", "tool", "verify", "answer"];
/** Events that say something about the world, not that the reader did something: they never wake the bot or postpone its sleep. */
const PASSIVE = new Set(["unread", "offline", "hold", "waiting-clear"]);
const PHASE_ALIAS = { thinking: "waiting" };

export function createDirector({ now = 0, reducedMotion = false, persona = NEUTRAL, instantHandoff = false } = {}) {
  let who = { ...NEUTRAL, ...persona };
  let table = bodyTable(who);
  let moods = MOODS_BY_ARCHETYPE[who.archetype] ?? MOODS_BY_ARCHETYPE.lead;
  const setPersona = next => { who = { ...NEUTRAL, ...next }; table = bodyTable(who); moods = MOODS_BY_ARCHETYPE[who.archetype] ?? MOODS_BY_ARCHETYPE.lead; };
  const m = {
    hand: null, glance: null,
    reduced: reducedMotion, quick: instantHandoff, lastActivity: now,
    turn: null, stinger: null, ended: null, last: null, unread: false, offline: false, listening: null,
    hover: { on: false, since: 0, used: false }, click: null, clicks: 0,
    introUntil: -Infinity,
    held: { state: table.idle, layer: "idle", pose: "idle", changedAt: -Infinity }
  };

  /** What the waiting-for-you pose does at `t`: nudging (wide) or resting, and whether it is over (then it holds a still frame). */
  function holdAt(t) {
    const since = t - m.ended.since;
    const k = Math.floor(since / T.NUDGE_EVERY);
    const nudging = !m.reduced && k >= 1 && k <= T.NUDGE_MAX && since - k * T.NUDGE_EVERY < T.NUDGE;
    const settled = m.reduced || since >= T.NUDGE_MAX * T.NUDGE_EVERY + T.NUDGE + MOOD_MORPH;
    return { nudging, settled };
  }

  /** Where the handoff is at `t` (null when none is under way): swaps the persona when its time has come and ends it when it is over. */
  function advance(t) {
    const h = m.hand;
    if (!h) return null;
    const age = t - h.t0;
    if (!h.to && age > HANDOFF.NEVER) { m.hand = null; return null; } // asked for, and nothing came (the page did not change): it stays what it was
    if (!h.swapped && age >= HANDOFF.SWAP && h.to) { setPersona(h.to); h.swapped = true; }
    const end = h.quiet ? HANDOFF.ENTER_AT : HANDOFF.SWIRL_END;
    if (age >= end) {
      if (h.unread && !h.quiet && !m.reduced) m.glance = { until: h.t0 + HANDOFF.SWIRL_END + HANDOFF.GLANCE };
      m.hand = null;
      return null;
    }
    if (!h.to) return { age, phase: "leave" }; // who comes is not known yet: the old aura has left, the body waits in its exit pose
    return { age, phase: age < HANDOFF.SWAP ? "leave" : age < HANDOFF.ENTER_AT ? "swap" : age < HANDOFF.ENTER_AT + HANDOFF.ENTER && !h.quiet ? "enter" : "settle" };
  }

  function desired(t) {
    if (m.turn) {
      const attending = !m.reduced && !m.turn.quiet && t < m.turn.since + T.ATTENTION;
      return { state: attending ? table.attention : table[m.turn.phase], layer: "work", pose: attending ? "attention" : m.turn.phase };
    }
    if (m.hand && m.hand.swapped && !m.hand.quiet && t - m.hand.t0 < HANDOFF.SWIRL_END) return { state: "swirl", layer: "handoff", pose: "handoff" };
    if (m.stinger && t < m.stinger.until) return { state: m.stinger.state, layer: "work", pose: "stinger" };
    if (m.ended?.outcome === "waiting" && !m.offline) {
      return { state: holdAt(t).nudging ? table.attention : table.hold, layer: "work", pose: "hold" };
    }
    if (m.offline) return { state: table.idle, layer: "idle", pose: "offline" };
    if (m.glance && t < m.glance.until && !m.reduced) return { state: table.idle, layer: "idle", pose: "glance" };
    if (m.unread) return { state: table.notify, layer: "notify", pose: "notify" };
    if (m.listening !== null) return { state: table.listen, layer: "idle", pose: "listen" };
    if (!m.reduced) {
      if (m.click && t < m.click.until) return { state: m.click.state, layer: "reaction", pose: "reaction" };
      if (m.hover.on && !m.hover.used && t < m.hover.since + T.HOVER) return { state: table.hover, layer: "reaction", pose: "reaction" };
      if (t - m.lastActivity >= T.SLEEP_AFTER) return { state: table.sleep, layer: "life", pose: "sleep" };
    }
    return { state: table.idle, layer: "idle", pose: "idle" };
  }

  return {
    send(event, t) {
      advance(t);
      if (!PASSIVE.has(event.type) && !(event.type === "phase" && event.phase === "idle")) m.lastActivity = t;
      switch (event.type) {
        case "turn-start":
          m.turn = { phase: "waiting", since: t, phaseSince: t, quiet: Boolean(event.quiet) };
          m.stinger = null; m.click = null; m.ended = null; m.listening = null; m.last = null;
          break;
        case "phase": {
          const phase = PHASE_ALIAS[event.phase] ?? event.phase;
          if (m.turn) {
            if (WORK_PHASES.includes(phase) && m.turn.phase !== phase) { m.turn.phase = phase; m.turn.phaseSince = t; }
          } else if (phase === "listening") { if (m.listening === null) m.listening = { since: t }; }
          else if (phase === "idle") m.listening = null;
          break;
        }
        case "turn-end": {
          const was = m.turn; m.turn = null;
          if (!was) break;
          m.last = { outcome: event.outcome, since: t }; // the aura keeps its own end beat (aura/track.mjs), longer than the nod and not cut by reduced motion
          // "waiting" stays until you answer (the next turn) or the card runs out (`waiting-clear`); "partial" is a short beat.
          m.ended = event.outcome === "waiting" ? { outcome: "waiting", since: t, until: Infinity }
            : event.outcome === "partial" ? { outcome: "partial", since: t, until: t + T.PARTIAL } : null;
          // Reduced motion has no beats: a finished turn shows nothing of its own (no wink), and a failed one keeps its "!" still frame until
          // the next turn (the error bar stays up that long too, design 6.9) instead of for two seconds.
          if (event.outcome === "done") m.stinger = m.reduced ? null : { state: table.success, until: t + T.SUCCESS };
          else if (event.outcome === "error") m.stinger = { state: table.error, until: m.reduced ? Infinity : t + T.ERROR };
          else m.stinger = null;
          break;
        }
        case "waiting-clear": if (m.ended?.outcome === "waiting") m.ended = null; break; // the card ran out / was answered elsewhere
        // The owner found the ball already in your court without having seen the turn end (a conversation restored on load, a bot switched to).
        case "hold": if (!m.turn && m.ended?.outcome !== "waiting") m.ended = { outcome: "waiting", since: t, until: Infinity }; break;
        case "offline": m.offline = Boolean(event.value); break;
        case "unread": m.unread = Boolean(event.value); break;
        case "hover":
          m.hover = event.value ? { on: true, since: t, used: false } : { on: false, since: 0, used: false };
          break;
        case "click": {
          const state = table.click[m.clicks++ % table.click.length];
          m.click = { state, until: t + (CLICK_FOR[state] ?? T.CLICK) };
          m.hover.used = true;
          break;
        }
        // The level of animation went to (or came back from) "lite", which has no swirl and no entrance: a handoff under way is over at once.
        case "instant-handoff": m.quick = Boolean(event.value); if (m.quick && m.hand) { if (m.hand.to) setPersona(m.hand.to); m.hand = null; } break;
        case "arrive": if (!m.reduced) m.introUntil = t + T.INTRO; break;
        // The click that asks for a switch is heard before the new line exists: the old aura leaves at once; the persona arrives with `handoff`.
        case "handoff-begin": if (!m.reduced && !m.quick && !m.hand) m.hand = { t0: Number.isFinite(event.at) ? Math.min(event.at, t) : t, fromAura: who.auraVariant, carry: null, to: null, swapped: false, quiet: false, unread: false }; break;
        case "persona": if (m.hand && !m.hand.swapped) m.hand.to = event.persona; else setPersona(event.persona); break;
        case "handoff": {
          const to = { ...NEUTRAL, ...event.persona }, at = Number.isFinite(event.at) ? Math.min(event.at, t) : t;
          // what belonged to the line that was left goes; the new line's own state arrives with the events that follow
          m.turn = null; m.stinger = null; m.ended = null; m.last = null; m.listening = null; m.click = null; m.glance = null;
          m.unread = false; m.offline = false; m.hover = { on: false, since: 0, used: false };
          if (m.reduced || m.quick) { setPersona(to); m.hand = null; break; } // reduced motion and "lite" have no handoff to play: the new bot is simply there
          const h = m.hand, quiet = Boolean(event.quiet), unread = Boolean(event.unread);
          if (h && !h.swapped) {
            // still in the exit: the one in between is never shown.  Who comes is known only now (the exit began at the click, before the page
            // changed): when that is late, the rest of the handoff still plays whole, from the swap on.
            if (!h.to && t - h.t0 > HANDOFF.SWAP) h.t0 = t - HANDOFF.SWAP;
            Object.assign(h, { to, quiet, unread });
          }
          else if (h) { // the one in between is on screen: leave it at once for the last target, from the pose it is in
            const age = t - h.t0, carry = handoffBody({ from: h.fromAura, to: who.auraVariant, age, quiet: h.quiet, carry: h.carry });
            m.hand = { t0: t - HANDOFF.SWAP, fromAura: who.auraVariant, carry, to, swapped: false, quiet, unread };
          } else m.hand = { t0: at, fromAura: who.auraVariant, carry: null, to, swapped: false, quiet, unread };
          advance(t);
          break;
        }
        default: break; // "activity": only the lastActivity touch above
      }
    },
    /** Resolve what to show at `now`. Reads must use a non-decreasing clock. */
    read(t) {
      advance(t);
      const want = desired(t);
      // Morph floor: a state just entered is kept for DWELL, whatever outranks it.
      // (Not under reduced motion: nothing morphs there, so there is nothing to protect, and a still frame must show the pose of the moment.)
      if (!m.reduced && want.state !== m.held.state && t - m.held.changedAt < T.DWELL) {
        return view(m.held.state, m.held.layer, m.held.pose, t, true, want);
      }
      if (want.state !== m.held.state) m.held = { state: want.state, layer: want.layer, pose: want.pose, changedAt: t };
      else { m.held.layer = want.layer; m.held.pose = want.pose; }
      return view(m.held.state, m.held.layer, m.held.pose, t, false, want);
    }
  };

  function gazeOf(pose) {
    switch (pose) {
      case "listen": case "verify": return "below";
      case "tool": return toolGaze(who.auraVariant);
      case "glance": return "below"; // toward the divider above the new messages
      case "hold": case "offline": return "front";
      case "idle": return who.restGaze;
      default: return "front"; // a body that owns its own gaze (orbit, wink, alert...): the engine ignores it there
    }
  }

  function view(state, layer, pose, t, dwelling, want) {
    const hand = advance(t) ?? null;
    const idle = state === table.idle;
    const phase = MOOD_PHASE[pose];
    // The face layer rides on work poses (and the listening pose); every other base is calm.
    const since = pose === "listen" ? m.listening?.since ?? t : pose === "hold" ? m.ended?.since ?? t : m.turn?.phaseSince ?? t;
    const seq = phase ? moods[phase] : null;
    // Reduced motion: `expression` stays calm (nothing rotates); `still` is the face a static frame of this pose wears (design 6.9).
    const expression = !phase || !seq || m.reduced ? CALM : moodAt(phase, Math.max(0, t - since) * who.tempo, who.archetype);
    const still = phase && seq ? seq[0] : CALM;
    const ended = m.ended && t < m.ended.until ? m.ended.outcome : null;
    const offline = pose === "offline";
    const asleep = state === table.sleep;
    const gaze = gazeOf(pose);
    const resting = !dwelling && (
      (asleep && want.state === table.sleep && t - m.held.changedAt >= T.SLEEP_FREEZE) ||
      offline ||
      (pose === "hold" && holdAt(t).settled && !m.reduced));
    return {
      state, layer, pose, follow: !m.reduced && idle && gaze === "follow", intro: idle && t < m.introUntil, expression, moodMorph: MOOD_MORPH, ended,
      still, gaze, tilt: idle && pose === "idle" && gaze === "ahead-right" ? 6 : 0, // a lean is a posture, not motion: reduced-motion still frames keep it
      waitingForUser: (pose === "hold" || (pose === "handoff" && m.ended?.outcome === "waiting")) && !(m.hand && !m.hand.swapped), // not on the body that is still leaving
      handoff: hand && { phase: hand.phase, age: hand.age, t: hand.phase === "enter" ? hand.age - HANDOFF.ENTER_AT : hand.age, from: m.hand.fromAura, to: m.hand.to ? who.auraVariant : null, quiet: m.hand.quiet, carry: m.hand.carry },
      outcome: m.last?.outcome ?? null, outcomeAge: m.last ? Math.max(0, t - m.last.since) : null,
      nod: ended === "partial" ? Math.min(1, Math.max(0, (t - m.ended.since) / T.PARTIAL)) : null,
      dim: offline, frozen: Boolean(resting),
      tempo: who.tempo, easing: who.easing, archetype: who.archetype, aura: who.auraVariant
    };
  }
}

/** First visit to a bot's chat in this page session plays the arrival; later visits don't. Reduced motion never consumes it.
 * `switching`: the avatar was already standing there for another bot (a handoff replaces the arrival, so the two never play together): the bot is
 * marked as met and nothing plays. */
export function shouldArrive(seen, botId, reducedMotion, switching = false) {
  if (!botId || reducedMotion || seen.has(botId)) return false;
  seen.add(botId);
  return !switching; // switching to a bot in the page session counts as having met it: the handoff plays instead of the arrival
}

/** Where the running turn is, read off the streaming transcript: waiting / tool / verify / answer (null when no turn runs).
 * A thin reading of turn-signals (which also knows listening, units and offline); "thinking" there is "waiting" here. */
export function turnPhase(chatState, messages) {
  if (chatState !== "sending") return null;
  const { phase } = turnSignal({ chatState, messages });
  return phase === "thinking" ? "waiting" : phase;
}

/** Chat state change -> director event (or null). The outcome of a finished turn is read off its last message.
 * Precedence: error (state error or a failed message) > cancel > waiting (waiting status or an unanswered card) >
 * partial (partially_succeeded) > done. */
export function turnTransition(prev, next, messages) {
  if (prev !== "sending" && next === "sending") return { type: "turn-start" };
  if (prev === "sending" && next !== "sending") {
    if (next === "error") return { type: "turn-end", outcome: "error" };
    const last = messages?.[messages.length - 1];
    if (last?.role === "assistant" && last.status === "failed") return { type: "turn-end", outcome: "error" };
    if (!last || last.role !== "assistant" || last.status === "cancelled") return { type: "turn-end", outcome: "cancel" };
    if (awaitsUser(last)) return { type: "turn-end", outcome: "waiting" };
    return { type: "turn-end", outcome: last.status === "partially_succeeded" ? "partial" : "done" };
  }
  return null;
}
