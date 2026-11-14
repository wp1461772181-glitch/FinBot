import { useEffect, useMemo, useState } from "react";
import { Check, ChevronRight, Circle, LoaderCircle, X } from "lucide-react";
import type { AgentChatMessage } from "../../api";
import { useLocale } from "../../i18n";
import { barModel, legacyToolChips, type StepChip } from "../../process-steps.mjs";
import { turnKey } from "../../panel-model.mjs";
import { usePanel } from "./panel-context";

const TICK_MS = 200;
const barClass = "inline-flex max-w-full flex-wrap items-center gap-x-1.5 gap-y-1 rounded-md text-left text-caption text-muted-foreground";
const chipClass = "inline-flex min-w-0 items-center gap-1 rounded-full border border-line bg-surface px-2 py-0.5 text-caption text-ink-2";

/** A step's state as a small mark: turning while it runs, a tick when done, a cross when it failed.  A step that finished with remarks is a plain hollow circle, never a warning. */
function StateMark({ state }: { state: StepChip["state"] }) {
  if (state === "running") return <LoaderCircle aria-hidden="true" className="size-3.5 shrink-0 text-bot motion-safe:animate-spin" />;
  if (state === "failed") return <X aria-hidden="true" className="size-3.5 shrink-0 text-danger" />;
  if (state === "warn" || state === "cancelled") return <Circle aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" />;
  return <Check aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />;
}

function Chip({ chip }: { chip: StepChip }) {
  const { t } = useLocale();
  return <span data-slot="step-chip" data-kind={chip.kind} data-state={chip.state} data-outcome={chip.outcome || undefined} className={chipClass}>
    <StateMark state={chip.state} />
    <span className="truncate">{t(chip.label)}{chip.suffix}{chip.outcome === "count" ? ` (${chip.count})` : ""}</span>
    {chip.outcome === "none" && <span className="shrink-0 text-muted-foreground">{t("无匹配")}</span>}
    {chip.outcome === "failed" && <span className="truncate text-muted-foreground">{chip.reasonKnown ? t(chip.reason) : chip.reason}</span>}
  </span>;
}

/**
 * The first cell of a running bar: three dots, what the turn is doing, the seconds since it started.  It is the place A3 puts the bot's own
 * trace of thinking; the rest of the bar does not depend on what is in it.
 */
function ThinkingSlot({ text, seconds }: { text: string; seconds: string }) {
  const { t } = useLocale();
  return <span data-slot="thinking-slot" className="inline-flex items-center gap-1.5 pr-1 text-caption text-muted-foreground">
    <span aria-hidden="true" className="steps-dots inline-flex items-center gap-0.5"><i /><i /><i /></span>
    <span>{text}</span>
    <span className="tabular-nums">{seconds} {t("秒")}</span>
  </span>;
}

/**
 * The process bar under a bot's answer (design 4.2, item 2).  While the turn runs it is a row of step chips that grows with the trace;
 * when the turn is over it folds to one line, 「已思考 12.4 秒 · 5 步」.  Either way it is one button: it opens the panel's 过程 tab on this round.
 * An answer from before the step graph shows only its time, or the old tool badges as chips, or nothing, as the old panel did.
 */
export function TurnSteps({ m, i, running, status }: { m: AgentChatMessage; i: number; running: boolean; status: string }) {
  const { t } = useLocale(), panel = usePanel();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, [running]);
  const model = barModel({ trace: m.trace, thinkingMs: m.thinking_ms, startedAt: m.started_at, running, now });
  const tools = useMemo(() => (m.trace?.length ? [] : legacyToolChips(m.tool_trace)), [m.trace, m.tool_trace]);
  const open = () => panel.showProcess(turnKey(m, i));
  const partial = m.status === "partially_succeeded";

  const reused = m.reused_sources ? <span data-slot="step-chip" data-kind="reused" className={chipClass}><Check aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />{t("复用已核实来源")}</span> : null;
  const toolChips = tools.length > 0 && <>{tools.map((tool) => <span key={tool.id} data-slot="step-chip" data-kind="tool" data-state={tool.state} className={chipClass}>
    <span className="truncate">{t(tool.label)} · {t(tool.status)}{tool.summary ? ` · ${tool.summary}` : ""}</span></span>)}</>;

  if (model.kind === "running") {
    const cells = <><ThinkingSlot text={status || t("思考中")} seconds={model.seconds} />{model.chips.map((chip) => <Chip key={chip.id} chip={chip} />)}{reused}</>;
    // Before the first event there is no round to open yet (i < 0): the bar only shows the line was taken.
    if (i < 0) return <div data-testid="turn-steps" data-state="running" data-chips="0" className={barClass}>{cells}</div>;
    return <button type="button" data-testid="turn-steps" data-state="running" data-chips={model.chips.length} className={`${barClass} cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-ring`} onClick={open}
      title={t("在右侧查看这一轮的过程")}>{cells}</button>;
  }
  const heading = `${t("已思考")} ${model.seconds} ${t("秒")}${model.steps > 0 ? ` · ${model.steps} ${t("步")}` : ""}${partial ? ` · ${t("部分来源可用")}` : ""}`;
  if (model.kind === "summary") {
    return <div className="flex flex-wrap items-center gap-1.5">
      <button type="button" data-testid="turn-steps" data-state="summary" data-steps={model.steps} className={`${barClass} cursor-pointer outline-none hover:text-ink-2 focus-visible:ring-2 focus-visible:ring-ring`} onClick={open} aria-label={`${heading} · ${t("在右侧查看这一轮的过程")}`}>
        <span>{heading}</span><ChevronRight aria-hidden="true" className="size-3.5" />
      </button>
      {reused}
    </div>;
  }
  if (model.kind === "time" || tools.length > 0 || reused) {
    return <div data-testid="turn-steps" data-state={model.kind === "time" ? "time" : "tools"} className="flex flex-wrap items-center gap-1.5 text-caption text-muted-foreground">
      {model.kind === "time" && <span>{heading}</span>}
      {toolChips}{reused}
    </div>;
  }
  return null;
}
