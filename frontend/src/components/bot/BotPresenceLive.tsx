// The live half of BotPresence (loaded after the first paint, see BotPresence.tsx).
// The bot standing in the chat: the one avatar that runs the whole interaction (gaze, hover / click reactions, the turn's poses, arrival,
// sleep, unread, listening, waiting for you, offline). The behaviour is in bloub-director.mjs / bloub-gaze.mjs / turn-signals.mjs
// (pure, unit-tested); this file wires DOM events and the chat state to them and hands the director to the body.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { createDirector, shouldArrive, turnTransition, type DirectorView } from "../../bloub-director.mjs";
import { resolveLook } from "../../bloub-look.mjs";
import { derivePersona, type Persona, type PersonaBot } from "../../bot-persona.mjs";
import { parseAvatar } from "../../orb.mjs";
import { awaiting, isOffline, turnSignal } from "../../turn-signals.mjs";
import { useBackendDown } from "../state/connectivity-store";
import { useLocale } from "../../i18n";
import { notify } from "../state/notify";
import { activateMotion, canWatch, downgradeNow, revertDowngrade } from "../../motion-control.mjs";
import { getMotion, subscribeMotion } from "../../motion-store.mjs";
import { playsSwirl } from "../../handoff-line.mjs";
import { BotAvatar } from "./BotAvatar";
import { BotBody, type BloubState, type LiveHandle, type WornLook } from "./BotBody";
import { currentIntent, subscribeIntent } from "../../app/chat/handoff-intent";
import { HANDOFF } from "../../handoff.mjs";
import { drive, pacer } from "./live-drive";
import { usePersona } from "./use-persona";
import { RAYON } from "../../bloub/repere";
import { auraFor } from "../../aura/index.mjs";
import { bodyMotion } from "../../aura/motion.mjs";
import { STILL_FINISH_SECONDS, auraPhaseOf, stillInput } from "../../aura/track.mjs";
import { tierOf } from "../../bot-sizes.mjs";
import { drawAura } from "./aura-paint";
export type { BotPresenceProps };

activateMotion(); // the device and the drop join the level (the first screen settled the system's setting and the reader's choice)

/** Bots whose arrival already played in this page session (module scope: survives remounts, resets on reload). */
const arrived = new Set<string>();
const nowSec = () => performance.now() / 1000;
/** The chat's message box (Composer.tsx): while it has focus and text the bot listens. */
const COMPOSER_ID = "agent-draft";

type Msg = { role?: string; content?: string; status?: string; clarification?: unknown; card_at?: number; tool_trace?: ReadonlyArray<{ status?: string; result?: unknown }>; trace?: ReadonlyArray<{ kind?: string; status?: string }>; failure?: { network?: boolean } };

interface BotPresenceProps {
  avatar: string | null | undefined; look?: unknown; name: string; seed?: string; arrivalKey?: string; size?: number;
  chatState: string; messages: ReadonlyArray<Msg>; unread?: boolean; onAcknowledge?: () => void; className?: string;
  /** What is typed in the message box (the bot listens while it has focus). */
  draft?: string;
  /** The bot's record, for its personality (the five existing bots are pinned, any other is derived from it). Absent: the default bot's. */
  bot?: PersonaBot | null;
}

export default function BotPresenceLive({ avatar, look: stored, name, seed, arrivalKey, size = 30, chatState, messages, unread = false, onAcknowledge, className = "", draft = "", bot }: BotPresenceProps) {
  const parsed = parseAvatar(avatar, name);
  const persona = usePersona(bot ?? { name: "FinBot" });
  const motion = useSyncExternalStore(subscribeMotion, getMotion), reduced = motion.level === "off", lite = motion.level === "lite";
  const backendDown = useBackendDown().down;
  // One director for as long as the avatar stands here, whichever bot it shows: a switch is the director's `handoff` event, not a new director.
  const director = useMemo(() => createDirector({ now: nowSec(), reducedMotion: reduced, persona, instantHandoff: !playsSwirl({ reduced, level: motion.level }) }), [reduced]); // eslint-disable-line react-hooks/exhaustive-deps
  const target = resolveLook(seed || name, avatar, stored, name);
  const [worn, setWorn] = useState<WornLook>({ shape: target.shape, color: target.color });
  const wornRef = useRef(worn); wornRef.current = worn;
  // `look.want` is the bot's own look; the body puts it on when the director says the new persona is in (live-drive.ts), and tells us through `onWear`.
  const live = useMemo<LiveHandle>(() => ({ director, pointer: null, units: 0, drive, look: { want: wornRef.current, worn: wornRef.current } }), [director]);
  live.pace ??= pacer(live);
  live.look!.want = { shape: target.shape, color: target.color }; live.look!.onWear = setWorn;
  // The look the owner wants changed without a handoff (the colour or shape picked in the bot's settings): a resting body is made to take it.
  useEffect(() => { live.wake?.(); }, [target.shape, target.color]); // eslint-disable-line react-hooks/exhaustive-deps
  // "lite" has no swirl and no entrance: the director is told when the level moves in or out of it (a director made while "off" is rebuilt anyway).
  useEffect(() => { director.send({ type: "instant-handoff", value: lite }, nowSec()); live.wake?.(); }, [lite, director]); // eslint-disable-line react-hooks/exhaustive-deps
  // The frame watch (design 6.9 P10): while the level can still drop (nothing chose it, it has not dropped this visit), the loop's frame intervals go
  // to a pure watch in a chunk of its own; two seconds of frames averaging over 24 ms take the page to "lite" for this visit, said once and undoable.
  const { t } = useLocale();
  useEffect(() => {
    if (!canWatch()) return;
    let gone = false;
    void import("../../motion-watch.mjs").then(({ createFrameWatch }) => {
      if (gone) return;
      const watch = createFrameWatch();
      live.frame = ms => {
        if (!watch.step(ms)) return;
        live.frame = undefined;
        if (downgradeNow()) notify.info(t("已为这台设备切到精简动画"), { description: t("可以在「设置 › 外观」里改动画强度。"), undo: { label: t("改回"), onClick: () => { revertDowngrade(); } } });
      };
    });
    return () => { gone = true; live.frame = undefined; };
  }, [motion.level, motion.source, live]); // eslint-disable-line react-hooks/exhaustive-deps
  const botKey = bot?.id ?? seed ?? name;
  const prevKey = useRef(botKey), prevPersona = useRef(persona);
  // Reduced motion: the director's view behind the static frame, with the bot it was read for (the first render for a bot that has just taken the
  // place has no view yet, like a body mounted for the first time: it never wears the one the bot before it had).
  const [stillRead, setStill] = useState<{ view: DirectorView; key: string } | null>(null);
  const [composerFocused, setComposerFocused] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const prevState = useRef(chatState);
  const ack = useRef(onAcknowledge); ack.current = onAcknowledge;
  const checked = useRef(false); // reduced motion: did this turn go through a check (its marks stay in the still aura)
  const finishTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(finishTimer.current), []);

  /** Every event goes through here: the director learns it, and a stopped loop (asleep, offline, settled) starts again to show it. */
  const send = (event: Parameters<typeof director.send>[0]) => { director.send(event, nowSec()); live.wake?.(); };
  // Reduced motion: the frame is the pose of the moment (the director has no timed beats then), re-read after every event.
  const refreshStill = () => { if (reduced) setStill({ view: director.read(nowSec()), key: botKey }); };

  // The chat page carries the bot's tempo for the parts of the page that use it (design 6.4: `--bot-tempo`); its colour is written there already.
  useEffect(() => { root.current?.closest<HTMLElement>("[data-slot=chat-page]")?.style.setProperty("--bot-tempo", String(persona.tempo)); }, [persona.tempo, botKey]);

  // Arrival: once per bot per page session (never under reduced motion).
  useEffect(() => { if (shouldArrive(arrived, arrivalKey || seed || name, reduced)) send({ type: "arrive" }); }, [director]); // eslint-disable-line react-hooks/exhaustive-deps

  // The bot standing here changed (design 6.7): the same body becomes the other bot.  The line it now shows is the baseline (the switch itself is
  // neither the end nor the start of a turn); a bot that is answering is joined quietly (no swirl, no entrance), one with unread messages gets
  // a glance at the divider afterwards.  The click that asked for it carries the time the clock of the handoff starts from.  The arrival (a turn
  // of the eyes) is for the first bot of a page and the big avatar of an empty line; here the bot only counts as met.
  useEffect(() => {
    if (prevKey.current !== botKey) {
      prevKey.current = botKey;
      shouldArrive(arrived, arrivalKey || botKey, reduced, true);
      prevState.current = chatState;
      send({ type: "handoff", persona, at: currentIntent(botKey)?.at ?? nowSec(), quiet: chatState === "sending", unread });
      if (chatState === "sending") send({ type: "turn-start", quiet: true });
      refreshStill();
    } else if (prevPersona.current !== persona) { send({ type: "persona", persona }); refreshStill(); }
    prevPersona.current = persona;
  }, [botKey, persona]); // eslint-disable-line react-hooks/exhaustive-deps

  // The click that asks for another bot is heard here before the page has changed: the old aura starts its exit at once (the persona arrives with the
  // `handoff` event above, when the new line is there).
  useEffect(() => subscribeIntent(() => {
    const intent = currentIntent();
    if (!intent || intent.to === String(botKey).toLowerCase()) return;
    live.ignoreCover?.(HANDOFF.SWIRL_END + 0.5); // a choice in the phone's drawer: the avatar behind it goes on (it is what the reader sees when the drawer is gone)
    send({ type: "handoff-begin", at: intent.at });
  }), [director, botKey]); // eslint-disable-line react-hooks/exhaustive-deps

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
    if (event?.type === "turn-start") checked.current = false;
    if (turn.phase === "verify") checked.current = true;
    // Reduced motion has no clock: a finished turn shows its closed shape for two seconds (with the check badge), then the frame is read again.
    if (reduced && event?.type === "turn-end" && (event.outcome === "done" || event.outcome === "partial")) {
      window.clearTimeout(finishTimer.current);
      finishTimer.current = window.setTimeout(refreshStill, STILL_FINISH_SECONDS * 1000 + 50);
    }
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

  useEffect(() => { send({ type: "unread", value: unread }); refreshStill(); }, [unread, director, botKey]); // eslint-disable-line react-hooks/exhaustive-deps

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
  // Reduced motion has no handoff: the still frame wears the bot's look at once, on a body of its own for each bot (`key` below): a still frame is a bot's
  // state seen from the start, never a blend from the one the previous bot was in.
  const look = reduced ? target : worn;
  const still = stillRead?.key === botKey ? stillRead.view : null;
  const hoverable = (e: ReactPointerEvent) => e.pointerType !== "touch";
  // Reduced motion: the aura is the static shape of the state (units still count), drawn into the still frame; TeslaBot's lean-back is a posture, so it stays.
  const tier = tierOf(size);
  const withAura = reduced && still && (tier === "M" || tier === "L");
  const auraStill = withAura ? (host: SVGGElement, paint: { ink: string }) => {
    const input = stillInput(still, turn.units, checked.current);
    drawAura(host, auraFor(still.aura)({ ...input, R: RAYON, tier }), paint, input.phase);
  } : undefined;
  const stillTilt = (still?.tilt ?? 0) + (withAura ? bodyMotion({ variant: still.aura, phase: auraPhaseOf(still, { still: true }), reduced: true }).tilt : 0);
  return <span ref={root} data-slot="bot-avatar" data-bot-color={look.color} data-pose={reduced ? still?.pose ?? "idle" : undefined} data-face={reduced ? still?.still : undefined} data-archetype={persona.archetype} className={`bot-orb bot-orb-live ${className}`.trim()} aria-hidden="true"
    style={{ width: size, height: size, "--bot-tempo": persona.tempo } as CSSProperties}
    onPointerEnter={e => { if (hoverable(e)) send({ type: "hover", value: true }); }}
    onPointerLeave={e => { if (hoverable(e)) send({ type: "hover", value: false }); }}
    onClick={() => { send({ type: "click" }); ack.current?.(); }}>
    {reduced
      ? <BotBody key={botKey} size={size} shape={look.shape} color={look.color} state={(still?.state ?? "idle") as BloubState} frozenAt={0} expression={still?.still} waiting={still?.waitingForUser} dim={still?.dim} gazeKind={still?.gaze} tilt={stillTilt} auraStill={auraStill} />
      : <BotBody size={size} shape={look.shape} color={look.color} live={live} />}
  </span>;
}
