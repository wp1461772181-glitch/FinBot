// The live half of BotPresence (loaded after the first paint, see BotPresence.tsx).
// The bot standing in the chat: the one avatar that runs the whole interaction (gaze, hover / click reactions, the turn's poses, arrival,
// sleep, unread, listening, waiting for you, offline). The behaviour is in bloub-director.mjs / bloub-gaze.mjs / turn-signals.mjs
// (pure, unit-tested); this file wires DOM events and the chat state to them and hands the director to the body.
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { createDirector, shouldArrive, turnTransition, type DirectorView } from "../../bloub-director.mjs";
import { resolveLook } from "../../bloub-look.mjs";
import { derivePersona, type Persona, type PersonaBot } from "../../bot-persona.mjs";
import { parseAvatar } from "../../orb.mjs";
import { awaiting, isOffline, turnSignal } from "../../turn-signals.mjs";
import { useBackendDown } from "../state/connectivity-store";
import { BotAvatar } from "./BotAvatar";
import { BotBody, type BloubState, type LiveHandle } from "./BotBody";
import { drive } from "./live-drive";
import { usePersona } from "./use-persona";
import type { AuraFn } from "./bot-painter";
export type { BotPresenceProps };

/** Bots whose arrival already played in this page session (module scope: survives remounts, resets on reload). */
const arrived = new Set<string>();
const nowSec = () => performance.now() / 1000;
/** The chat's message box (Composer.tsx): while it has focus and text the bot listens. */
const COMPOSER_ID = "agent-draft";

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches));
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

type Msg = { role?: string; content?: string; status?: string; clarification?: unknown; card_at?: number; tool_trace?: ReadonlyArray<{ status?: string; result?: unknown }>; trace?: ReadonlyArray<{ kind?: string; status?: string }>; failure?: { network?: boolean } };

interface BotPresenceProps {
  avatar: string | null | undefined; look?: unknown; name: string; seed?: string; arrivalKey?: string; size?: number;
  chatState: string; messages: ReadonlyArray<Msg>; unread?: boolean; onAcknowledge?: () => void; className?: string;
  /** What is typed in the message box (the bot listens while it has focus). */
  draft?: string;
  /** The bot's record, for its personality (the five existing bots are pinned, any other is derived from it). Absent: the default bot's. */
  bot?: PersonaBot | null;
  aura?: AuraFn;
}

export default function BotPresenceLive({ avatar, look: stored, name, seed, arrivalKey, size = 30, chatState, messages, unread = false, onAcknowledge, className = "", draft = "", bot, aura }: BotPresenceProps) {
  const parsed = parseAvatar(avatar, name);
  const persona = usePersona(bot ?? { name: "FinBot" });
  const reduced = useReducedMotion();
  const backendDown = useBackendDown().down;
  const director = useMemo(() => createDirector({ now: nowSec(), reducedMotion: reduced, persona }), [reduced, persona]);
  const live = useMemo<LiveHandle>(() => ({ director, pointer: null, units: 0, drive }), [director]);
  const [still, setStill] = useState<DirectorView | null>(null); // reduced motion: the director's view behind the static frame
  const [composerFocused, setComposerFocused] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const prevState = useRef(chatState);
  const ack = useRef(onAcknowledge); ack.current = onAcknowledge;

  /** Every event goes through here: the director learns it, and a stopped loop (asleep, offline, settled) starts again to show it. */
  const send = (event: Parameters<typeof director.send>[0]) => { director.send(event, nowSec()); live.wake?.(); };
  // Reduced motion: the frame is the pose of the moment (the director has no timed beats then), re-read after every event.
  const refreshStill = () => { if (reduced) setStill(director.read(nowSec())); };

  // The chat page carries the bot's tempo for the parts of the page that use it (design 6.4: `--bot-tempo`); its colour is written there already.
  useEffect(() => { root.current?.closest<HTMLElement>("[data-slot=chat-page]")?.style.setProperty("--bot-tempo", String(persona.tempo)); }, [persona.tempo]);

  // Arrival: once per bot per page session (never under reduced motion).
  useEffect(() => { if (shouldArrive(arrived, arrivalKey || seed || name, reduced)) send({ type: "arrive" }); }, [director]); // eslint-disable-line react-hooks/exhaustive-deps

  // Turn lifecycle. Mounting onto a running turn (switching back to a bot that is still answering) skips the "noticed you" beat.
  useEffect(() => {
    if (chatState === "sending" && prevState.current === "sending") send({ type: "turn-start", quiet: true });
  }, [director]); // eslint-disable-line react-hooks/exhaustive-deps

  const offline = isOffline({ backendDown, chatState, messages });
  const turn = turnSignal({ chatState, messages, draft, composerFocused, offline });
  const waitingSince = awaiting(messages, Date.now());
  useEffect(() => {
    const event = turnTransition(prevState.current, chatState, messages);
    prevState.current = chatState;
    if (event) send(event);
    live.units = turn.units;
    send({ type: "offline", value: offline });
    send({ type: "phase", phase: turn.phase });
    // The ball is in your court (also on a conversation found that way) until the card is answered or runs out.
    if (chatState !== "sending") send(waitingSince.waiting ? { type: "hold" } : { type: "waiting-clear" });
    refreshStill();
  }, [chatState, messages, director, turn.phase, offline, waitingSince.waiting]); // eslint-disable-line react-hooks/exhaustive-deps
  // A card that runs out while the page is open clears the pose at that moment.
  useEffect(() => {
    if (waitingSince.expiresAt === null || !waitingSince.waiting) return;
    const timer = window.setTimeout(() => { send({ type: "waiting-clear" }); refreshStill(); }, Math.max(0, waitingSince.expiresAt - Date.now()) + 50);
    return () => window.clearTimeout(timer);
  }, [waitingSince.expiresAt, waitingSince.waiting, director]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { send({ type: "unread", value: unread }); refreshStill(); }, [unread, director]); // eslint-disable-line react-hooks/exhaustive-deps

  // The composer's focus (listening).
  useEffect(() => {
    const test = (e: Event) => (e.target as Element | null)?.id === COMPOSER_ID;
    const on = (e: Event) => { if (test(e)) setComposerFocused(true); };
    const off = (e: Event) => { if (test(e)) setComposerFocused(false); };
    document.addEventListener("focusin", on); document.addEventListener("focusout", off);
    setComposerFocused(document.activeElement?.id === COMPOSER_ID);
    return () => { document.removeEventListener("focusin", on); document.removeEventListener("focusout", off); };
  }, []);

  // Page-level activity (wakes it from sleep) and the pointer for the gaze. Touch has no hovering pointer: ignored.
  useEffect(() => {
    if (reduced) return;
    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      live.pointer = { x: e.clientX, y: e.clientY, at: nowSec() };
      send({ type: "activity" });
    };
    const onAct = () => { send({ type: "activity" }); ack.current?.(); };
    const onLeave = () => { live.pointer = null; };
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerdown", onAct, { passive: true });
    window.addEventListener("keydown", onAct);
    document.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onAct);
      window.removeEventListener("keydown", onAct);
      document.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onLeave);
      live.pointer = null;
    };
  }, [director, live, reduced]); // eslint-disable-line react-hooks/exhaustive-deps

  if (parsed.kind === "text") return <BotAvatar avatar={avatar} look={stored} name={name} seed={seed} size={size} className={className} />;
  const look = resolveLook(seed || name, avatar, stored, name);
  const hoverable = (e: ReactPointerEvent) => e.pointerType !== "touch";
  return <span ref={root} data-slot="bot-avatar" data-bot-color={look.color} data-archetype={persona.archetype} className={`bot-orb bot-orb-live ${className}`.trim()} aria-hidden="true"
    style={{ width: size, height: size, "--bot-tempo": persona.tempo } as CSSProperties}
    onPointerEnter={e => { if (hoverable(e)) send({ type: "hover", value: true }); }}
    onPointerLeave={e => { if (hoverable(e)) send({ type: "hover", value: false }); }}
    onClick={() => { send({ type: "click" }); ack.current?.(); }}>
    {reduced
      ? <BotBody size={size} shape={look.shape} color={look.color} state={(still?.state ?? "idle") as BloubState} frozenAt={0} expression={still?.still} waiting={still?.waitingForUser} dim={still?.dim} gazeKind={still?.gaze} tilt={still?.tilt} />
      : <BotBody size={size} shape={look.shape} color={look.color} live={live} aura={aura} />}
  </span>;
}
