// The rehearsal ("试演台", design 6.9): a big preview of the bot with the personality it has now, a few lines of a made-up thread (for the thinking trace,
// the caret and the closing line), and a row of buttons: press one and the bot plays that state.  It runs the REAL parts (the director, the persona, the
// aura, the painter, the signature CSS); only the events come from buttons instead of a chat.  Nothing here asks the backend for anything or changes a
// bot: it is a mirror.  The level of animation of the preview is its own (the page's setting is not touched); the system's reduced motion holds here too.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLocale } from "../../i18n";
import { RAYON } from "../../bloub/repere";
import { createDirector, type DirectorView } from "../../bloub-director.mjs";
import { resolveLook, type BloubLook } from "../../bloub-look.mjs";
import { PERSONA_PRESETS, derivePersona, readOverrides, readVolatility, trackedSymbol, type Persona, type PersonaBot } from "../../bot-persona.mjs";
import { auraFor } from "../../aura/index.mjs";
import { bodyMotion } from "../../aura/motion.mjs";
import { auraPhaseOf, stillInput } from "../../aura/track.mjs";
import { signatureOf } from "../../signature-pick.mjs";
import { getMotion, subscribeMotion } from "../../motion-store.mjs";
import type { MotionLevel } from "../../motion-level.mjs";
import { Segmented } from "../Segmented";
import { BotAvatar } from "./BotAvatar";
import { BotBody, type BloubState, type LiveHandle, type WornLook } from "./BotBody";
import { drawAura } from "./aura-paint";
import { drive, pacer } from "./live-drive";
import { playScenario, type Scenario } from "./rehearsal-scenarios";
import { ARCHETYPE_NAMES } from "./PersonaPicker";
import { usePersona } from "./use-persona";

/** A bot as the rehearsal needs it: enough for its personality and its look. */
export interface StudioBot extends PersonaBot { id: string; name: string; avatar?: string | null; look?: unknown }

const SIZE = 144;
const nowSec = () => performance.now() / 1000;
const storage = () => { try { return window.localStorage; } catch { return null; } };
/** The buttons, in order: [scenario key, label (an i18n key)]. */
export const STATES: ReadonlyArray<readonly [string, string]> = [
  ["idle", "待机"], ["listening", "聆听"], ["thinking", "思考"], ["tool1", "工具 ×1"], ["tool3", "工具 ×3"], ["verify", "核验"], ["answer", "输出"],
  ["waiting", "等你"], ["done", "完成"], ["partial", "部分完成"], ["failed", "失败"]
];
const LEVEL_NAMES: Record<MotionLevel, string> = { full: "完整动画", lite: "精简动画", off: "关闭动画" };
const SAMPLE_USER = "AAPL 最近一个季度的财报怎么样？";
const SAMPLE_ANSWER = "营收同比增长 12%，服务业务毛利率继续上行 [1]";

const lookOf = (bot: StudioBot, look?: BloubLook | null): WornLook => { const l = resolveLook(bot.id, bot.avatar ?? "", look ?? bot.look, bot.name); return { shape: l.shape, color: l.color }; };
/** What another bot's personality is: its record, the volatility stored for it, and what this browser changed. */
const personaOf = (bot: StudioBot): Persona => {
  const symbol = trackedSymbol(bot), store = storage();
  return derivePersona(bot, { volatility: symbol ? readVolatility(store, bot.id, symbol) : null, overrides: readOverrides(store, bot.id) });
};

export function Rehearsal({ bot, look, others }: { bot: StudioBot; look?: BloubLook | null; others: ReadonlyArray<StudioBot> }) {
  const { t } = useLocale();
  const own = usePersona(bot);
  const site = useSyncExternalStore(subscribeMotion, getMotion);
  const systemOff = site.source === "system";
  const [level, setLevel] = useState<MotionLevel>(site.level);
  const [before, setBefore] = useState<MotionLevel>("full"); // the level the "减少动效" switch goes back to
  const effective: MotionLevel = systemOff ? "off" : level;
  const reduced = effective === "off";

  // Who the preview shows: the bot itself, or (after 切换) the one it became.
  const targets = useMemo<StudioBot[]>(() => {
    const real = others.filter(other => other.id !== bot.id);
    return real.length ? real : PERSONA_PRESETS.filter(preset => preset.id !== bot.id).map(preset => ({ id: preset.id, name: preset.name }));
  }, [others, bot.id]);
  const [targetId, setTargetId] = useState(() => targets[0]?.id ?? "");
  const [away, setAway] = useState<string | null>(null); // the id of the bot the preview has become, null: itself
  const awayBot = away ? targets.find(target => target.id === away) ?? null : null;
  const wearer: StudioBot = awayBot ?? bot;
  const awayPersona = useMemo(() => (awayBot ? personaOf(awayBot) : null), [awayBot]);
  const wearerPersona = awayPersona ?? own;
  const want = lookOf(wearer, awayBot ? null : look);
  const [worn, setWorn] = useState<WornLook>(want);

  const [scenario, setScenario] = useState("idle");
  const [announced, setAnnounced] = useState("");
  const planRef = useRef<Scenario | null>(null);
  const timers = useRef<number[]>([]);
  const clearTimers = () => { timers.current.forEach(id => window.clearTimeout(id)); timers.current = []; };
  useEffect(() => clearTimers, []);

  // One director for as long as the preview stands here (a switch is its `handoff` event).  "off" makes a reduced one (no clock; still frames).
  const director = useMemo(() => createDirector({ now: nowSec(), reducedMotion: reduced, persona: wearerPersona, instantHandoff: effective === "lite" }), [reduced]); // eslint-disable-line react-hooks/exhaustive-deps
  const live = useMemo<LiveHandle>(() => { const h: LiveHandle = { director, pointer: null, units: 0, drive, look: { want, worn: want } }; h.pace = pacer(h); return h; }, [director]); // eslint-disable-line react-hooks/exhaustive-deps
  live.level = effective === "lite" ? "lite" : "full";
  live.look!.want = want; live.look!.onWear = setWorn;
  const [still, setStill] = useState<DirectorView | null>(null);
  const refreshStill = () => { if (reduced) setStill(director.read(nowSec())); };
  useEffect(() => { director.send({ type: "instant-handoff", value: effective === "lite" }, nowSec()); live.wake?.(); }, [effective, director]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { live.wake?.(); }, [want.shape, want.color]); // eslint-disable-line react-hooks/exhaustive-deps
  // The reader's edits to this bot's personality are seen on the same body at once, silently (the director's `persona` event).
  const lastPersona = useRef(wearerPersona);
  useEffect(() => {
    if (lastPersona.current === wearerPersona) return;
    lastPersona.current = wearerPersona;
    director.send({ type: "persona", persona: wearerPersona }, nowSec());
    live.wake?.(); refreshStill();
  }, [wearerPersona]); // eslint-disable-line react-hooks/exhaustive-deps
  // A new director (the level went to or from "off"): back to rest.
  useEffect(() => { clearTimers(); setScenario("idle"); planRef.current = null; setStill(reduced ? director.read(nowSec()) : null); }, [director]); // eslint-disable-line react-hooks/exhaustive-deps

  const label = (key: string) => t(STATES.find(([name]) => name === key)?.[1] ?? "待机");
  const play = (name: string) => {
    clearTimers();
    setScenario(name);
    setAnnounced(`${t("正在演示")}：${label(name)}`);
    const plan = playScenario(name, [live], { now: nowSec, reduced, timers: timers.current });
    planRef.current = plan;
    refreshStill();
  };
  const switchTo = () => {
    const to = away ? null : targets.find(target => target.id === targetId) ?? targets[0] ?? null; // a second press goes back
    clearTimers();
    const next: StudioBot = to ?? bot, persona = to ? personaOf(to) : own, nextLook = lookOf(next, to ? null : look);
    live.look!.want = nextLook; live.look!.onWear = setWorn;
    director.send({ type: "handoff", persona, at: nowSec() }, nowSec());
    live.units = 0;
    if (reduced) setWorn(nextLook);
    lastPersona.current = persona;
    setAway(to ? to.id : null);
    setScenario("switch");
    setAnnounced(`${t("正在演示")}：${t("切换到另一个 bot")} → ${next.name}`);
    planRef.current = null;
    live.wake?.(); refreshStill();
  };
  const toggleReduced = () => { if (effective === "off") setLevel(before); else { setBefore(effective); setLevel("off"); } };

  // --- what is drawn ---
  const view = reduced ? still : null;
  const plan = planRef.current;
  const auraStill = reduced && view ? (host: SVGGElement, paint: { ink: string }) => {
    const v = view.outcome === "done" || view.outcome === "partial" ? { ...view, outcomeAge: 0 } : view;
    const input = stillInput(v, plan?.units ?? 0, plan?.checked ?? false);
    drawAura(host, auraFor(wearerPersona.auraVariant)({ ...input, R: RAYON, tier: "L" }), paint, input.phase);
  } : undefined;
  const tilt = view ? view.tilt + bodyMotion({ variant: wearerPersona.auraVariant, phase: auraPhaseOf(view, { still: true }), reduced: true }).tilt : 0;
  const shown = reduced ? want : worn;
  const sig = signatureOf(wearerPersona);
  const phase = scenario;
  const answering = phase === "answer";
  const ended = phase === "done" || phase === "partial" || phase === "failed";

  return (
    <div data-slot="rehearsal" data-scenario={scenario} data-level={effective} data-wearer={wearer.id} className="grid gap-3">
      <figure data-testid="rehearsal-stage" data-bot-color={shown.color} className="m-0 grid place-items-center rounded-md border border-line bg-surface px-3 py-10">
        <span data-slot="bot-avatar" data-bot-color={shown.color} data-archetype={wearerPersona.archetype} className="bot-orb" aria-hidden="true" style={{ width: SIZE, height: SIZE }}>
          {reduced
            ? <BotBody key={wearer.id} size={SIZE} shape={shown.shape} color={shown.color} state={(view?.state ?? "idle") as BloubState} frozenAt={0} expression={view?.still} waiting={view?.waitingForUser} dim={view?.dim} gazeKind={view?.gaze} tilt={tilt} auraStill={auraStill} />
            : <BotBody size={SIZE} shape={shown.shape} color={shown.color} live={live} />}
        </span>
        <figcaption data-testid="rehearsal-wearer" className="pt-10 text-center text-small text-muted-foreground">
          <strong className="text-ink">{wearer.name}</strong> · {t(ARCHETYPE_NAMES[wearerPersona.archetype])}
        </figcaption>
      </figure>

      <p role="status" data-testid="rehearsal-status" className="m-0 min-h-[22px] text-small text-ink">{announced}</p>

      <div role="group" aria-label={t("状态")} data-testid="rehearsal-states" className="flex flex-wrap gap-1.5">
        {STATES.map(([name, key]) => (
          <Button key={name} type="button" size="sm" className="max-sm:h-11" variant={scenario === name ? "default" : "outline"} aria-pressed={scenario === name} data-scenario={name} onClick={() => play(name)}>{t(key)}</Button>
        ))}
      </div>

      <div data-testid="rehearsal-switch-row" className="flex flex-wrap items-center gap-1.5">
        <Select value={targetId} onValueChange={setTargetId} disabled={Boolean(away)}>
          <SelectTrigger data-testid="rehearsal-target" aria-label={t("切换到哪个 bot")} className="h-8 w-40 rounded-sm border-line bg-surface px-2.5 text-small text-ink data-[size=default]:h-8 max-sm:data-[size=default]:h-11">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {targets.map(target => <SelectItem key={target.id} value={target.id}>
              <span className="flex items-center gap-2"><BotAvatar avatar={target.avatar} look={target.look} name={target.name} seed={target.id} size={20} />{target.name}</span>
            </SelectItem>)}
          </SelectContent>
        </Select>
        <Button type="button" size="sm" className="max-sm:h-11" variant={scenario === "switch" ? "default" : "outline"} data-scenario="switch" data-testid="rehearsal-switch" disabled={!targets.length} onClick={switchTo}>
          {away ? `${t("换回")} ${bot.name}` : t("切换到另一个 bot")}
        </Button>
      </div>

      <Segmented<MotionLevel> name={`rehearsal-level-${bot.id}`} testid="rehearsal-level" legend={t("预览的动画强度")} value={effective} onChange={setLevel}
        options={(["full", "lite", "off"] as const).map(value => ({ value, label: t(LEVEL_NAMES[value]), disabled: systemOff && value !== "off" }))} />
      <label className="flex min-h-8 w-fit cursor-pointer items-center gap-2 text-small text-ink max-sm:min-h-11">
        <input type="checkbox" data-testid="rehearsal-reduced" checked={effective === "off"} disabled={systemOff} onChange={toggleReduced} className="size-4 accent-[var(--accent)]" />
        {t("减少动效")}
      </label>
      <p className="m-0 text-small text-muted-foreground">
        {systemOff ? t("系统开了「减少动效」，预览固定为关闭。") : t("这两项只改预览，不改整站的动画强度。")}
      </p>

      <div data-testid="rehearsal-thread" data-trace={sig.trace} data-caret={sig.cursor} data-bot-color={shown.color} data-motion={effective === "off" ? "off" : undefined}
        style={{ "--bot-tempo": wearerPersona.tempo } as CSSProperties} className="grid gap-2 rounded-md border border-line bg-surface p-3">
        <p className="m-0 w-fit max-w-full self-end justify-self-end rounded-md bg-sunken px-2.5 py-1.5 text-small text-ink">{t(SAMPLE_USER)}</p>
        <div className="grid gap-1.5 text-small text-ink">
          {phase === "thinking" && <p data-testid="thread-thinking" className="m-0 flex items-center gap-2 text-muted-foreground"><span className="think-trace" aria-hidden="true" data-slot="think-trace"><i /><i /><i /></span>{t("思考中")}</p>}
          {(phase === "tool1" || phase === "tool3") && <p data-testid="thread-tools" className="m-0 flex items-center gap-2 text-muted-foreground"><span className="think-trace" aria-hidden="true" data-slot="think-trace"><i /><i /><i /></span>{t("调用工具")} · {phase === "tool1" ? 1 : 3}</p>}
          {phase === "verify" && <p data-testid="thread-verify" className="m-0 text-muted-foreground">{t("核验中")}</p>}
          {phase === "listening" && <p className="m-0 text-muted-foreground">{t("正在听你说…")}</p>}
          {(answering || ended) && <div className="chat-prose" data-streaming={answering ? "" : undefined}><p className="m-0">{t(SAMPLE_ANSWER)}</p></div>}
          {phase === "waiting" && <p data-testid="thread-waiting" className="m-0 rounded-sm border border-action bg-action-soft px-2.5 py-1.5">{t("等你确认：要把这条加入自选吗？")}</p>}
          {phase === "failed" && <p data-testid="thread-failed" className="m-0 text-danger">{t("这一轮没有完成。")}</p>}
          {/* the closing line, as app/chat/DoneLine draws it (its CSS is styles/bots-signature.css) */}
          {ended && <div data-testid="done-line" data-state={phase === "done" ? "done" : phase === "partial" ? "partial" : "failed"} aria-hidden="true" className="done-line">{phase !== "failed" && <span data-slot="done-sweep" className="done-sweep" />}</div>}
          {(phase === "idle" || phase === "switch") && <p className="m-0 text-muted-foreground">{t("点上面的状态按钮，看它怎么演。")}</p>}
        </div>
      </div>
    </div>
  );
}
