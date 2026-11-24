import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { AgentChatMessage } from "../../api/conversations";
import { useLocale } from "../../i18n";
import { barModel } from "../../process-steps.mjs";
import { foldedLine, type ProgressItem, type ProgressModel } from "../../turn-progress.mjs";
import { ThinkingSlot, useNow } from "./TurnSteps";

const MARKS: Record<ProgressItem["status"], string> = { done: "\u2611", doing: "\u25D0", pending: "\u2610", failed: "\u2612" };
const MARK_WORDS: Record<ProgressItem["status"], string> = { done: "已完成", doing: "进行中", pending: "等待中", failed: "失败" };
const barClass = "inline-flex max-w-full flex-wrap items-center gap-x-1.5 gap-y-1 rounded-md text-left text-caption text-muted-foreground";

/** What the kernel said, one line each, stacked in the order it said them: they never replace each other. */
function Sentences({ lines }: { lines: string[] }) {
  if (lines.length === 0) return null;
  return <ul data-slot="turn-sentences" className="flex flex-col gap-0.5 text-caption text-muted-foreground">
    {lines.map((line, index) => <li key={index} className="whitespace-pre-wrap break-words">{line}</li>)}
  </ul>;
}

/** The checklist: a tick for done, a half circle for the item in progress (the one to look at), an empty box for the rest. */
function Checklist({ items }: { items: ProgressItem[] }) {
  const { t } = useLocale();
  if (items.length === 0) return null;
  return <ul data-slot="turn-checklist" className="flex flex-col gap-0.5 text-caption">
    {items.map((item, index) => <li key={index} data-status={item.status} className={`flex items-baseline gap-1.5 ${item.status === "doing" ? "font-medium text-ink" : "text-muted-foreground"}`}>
      <span aria-hidden="true" className="shrink-0">{MARKS[item.status]}</span>
      <span className="sr-only">{t(MARK_WORDS[item.status])}</span>
      <span className="min-w-0 break-words">{item.text}</span>
    </li>)}
  </ul>;
}

/**
 * The progress of a kernel turn (design 4.5), shown where the process bar is shown for the old engine.  Running: the earlier sentences, the
 * checklist, then the thinking slot with the newest sentence.  Finished: one line (「已思考 12.4 秒 · 查了 3 次 · 清单 2/3 项 · 中档」)
 * that opens the sentences and the checklist in place.
 */
export function TurnProgress({ m, model, running, status }: { m: AgentChatMessage; model: ProgressModel; running: boolean; status: string }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const now = useNow(running);
  const bar = barModel({ trace: m.trace, thinkingMs: m.thinking_ms, startedAt: m.started_at, running, now });
  if (running) {
    return <div data-testid="turn-progress" data-state="running" className="flex min-w-0 flex-col gap-1.5">
      <Sentences lines={model.sentences} />
      <Checklist items={model.items} />
      <div className={barClass}><ThinkingSlot text={model.current ?? (status || t("思考中"))} seconds={bar.seconds} /></div>
    </div>;
  }
  const pieces = foldedLine(model, bar.kind === "none" ? undefined : bar.seconds, t);
  const hasBody = model.sentences.length > 0 || model.items.length > 0;
  const heading = pieces.join(" \u00B7 ");
  return <div data-testid="turn-progress" data-state={open ? "open" : "folded"} className="flex min-w-0 flex-col gap-1.5">
    <button type="button" aria-expanded={hasBody ? open : undefined} disabled={!hasBody}
      className={`${barClass} self-start outline-none focus-visible:ring-2 focus-visible:ring-ring ${hasBody ? "cursor-pointer hover:text-ink-2" : ""}`} onClick={() => setOpen((x) => !x)}>
      <span>{heading}</span>
      {hasBody && <ChevronRight aria-hidden="true" className={`size-3.5 transition-transform ${open ? "rotate-90" : ""}`} />}
    </button>
    {open && <><Sentences lines={model.sentences} /><Checklist items={model.items} /></>}
  </div>;
}
