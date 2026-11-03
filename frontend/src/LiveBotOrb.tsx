// The chat page's main bot avatar: the only one that runs the full interaction loop (gaze follow, hover / click
// reactions, turn-lifecycle choreography, arrival, sleep, unread notification). Sidebar and list avatars stay the
// light BotOrb. The behaviour lives in bloub-director.mjs / bloub-gaze.mjs (pure, unit-tested); this file only wires
// DOM events and the chat state to them.
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { BloubAvatar, type BloubState, type LiveHandle } from "./BloubAvatar";
import { BotOrb } from "./BotOrb";
import { createDirector, shouldArrive, turnPhase, turnTransition } from "./bloub-director.mjs";
import { resolveLook } from "./bloub-look.mjs";
import { parseAvatar } from "./orb.mjs";

/** Bots whose arrival already played in this page session (module scope: survives remounts, resets on reload). */
const arrived = new Set<string>();
const nowSec = () => performance.now() / 1000;

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

type Msg = { role?: string; content?: string; status?: string; tool_trace?: ReadonlyArray<{ status?: string }> };

export function LiveBotOrb({ avatar, look: stored, name, seed, size = 30, chatState, messages, unread = false, onAcknowledge, className = "" }: {
  avatar: string | null | undefined; look?: unknown; name: string; seed?: string; size?: number;
  chatState: string; messages: ReadonlyArray<Msg>; unread?: boolean; onAcknowledge?: () => void; className?: string;
}) {
  const parsed = parseAvatar(avatar, name);
  const reduced = useReducedMotion();
  const director = useMemo(() => createDirector({ now: nowSec(), reducedMotion: reduced }), [reduced]);
  const live = useMemo<LiveHandle>(() => ({ director, pointer: null }), [director]);
  const [still, setStill] = useState<string>("idle"); // reduced motion: state of the static frame
  const prevState = useRef(chatState);
  const ack = useRef(onAcknowledge); ack.current = onAcknowledge;

  const refreshStill = () => {
    if (!reduced) return;
    setStill(director.read(nowSec()).state);
    window.setTimeout(() => setStill(director.read(nowSec()).state), 2200); // after the longest stinger (error, 2 s)
  };

  // Arrival: once per bot per page session (never under reduced motion).
  useEffect(() => { if (shouldArrive(arrived, seed || name, reduced)) director.send({ type: "arrive" }, nowSec()); }, [director]); // eslint-disable-line react-hooks/exhaustive-deps

  // Turn lifecycle. Mounting onto a running turn (switching back to a bot that is still answering) skips the "noticed you" beat.
  useEffect(() => {
    const t = nowSec();
    if (chatState === "sending" && prevState.current === "sending") director.send({ type: "turn-start", quiet: true }, t);
  }, [director]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const t = nowSec(), event = turnTransition(prevState.current, chatState, messages);
    prevState.current = chatState;
    if (event) director.send(event, t);
    const phase = turnPhase(chatState, messages);
    if (phase) director.send({ type: "phase", phase }, t);
    refreshStill();
  }, [chatState, messages, director]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { director.send({ type: "unread", value: unread }, nowSec()); refreshStill(); }, [unread, director]); // eslint-disable-line react-hooks/exhaustive-deps

  // Page-level activity (wakes it from sleep) and the pointer for the gaze. Touch has no hovering pointer: ignored.
  useEffect(() => {
    if (reduced) return;
    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      live.pointer = { x: e.clientX, y: e.clientY, at: nowSec() };
      director.send({ type: "activity" }, nowSec());
    };
    const onAct = () => { director.send({ type: "activity" }, nowSec()); ack.current?.(); };
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
  }, [director, live, reduced]);

  if (parsed.kind === "text") return <BotOrb avatar={avatar} look={stored} name={name} seed={seed} size={size} className={className} />;
  const look = resolveLook(seed || name, avatar, stored);
  const hoverable = (e: ReactPointerEvent) => e.pointerType !== "touch";
  return <span className={`bot-orb bot-orb-live ${className}`.trim()} aria-hidden="true" style={{ width: size, height: size }}
    onPointerEnter={e => { if (hoverable(e)) director.send({ type: "hover", value: true }, nowSec()); }}
    onPointerLeave={e => { if (hoverable(e)) director.send({ type: "hover", value: false }, nowSec()); }}
    onClick={() => { director.send({ type: "click" }, nowSec()); ack.current?.(); }}>
    {reduced
      ? <BloubAvatar size={size} shape={look.shape} color={look.color} state={still as BloubState} frozenAt={0} />
      : <BloubAvatar size={size} shape={look.shape} color={look.color} live={live} />}
  </span>;
}
