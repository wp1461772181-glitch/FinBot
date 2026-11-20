// A short row of steps (design 5.4): which are done, which one is current, whether the current one is waiting for something outside the page.  Used by the
// Telegram binding (save the token → make a code → wait for the message); the other multi-step forms of the redesign reuse it.
import type { ReactNode } from "react";
import { Check, LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale, comma } from "../i18n";

export type Step = { id: string; label: ReactNode };

/**
 * `current` is the index of the step being done; a number equal to the step count means all are done.  `waiting` marks the current step as one that
 * finishes on its own (the page is polling for it): it shows a turning mark instead of its number.  The list is an `<ol>`; the current step has
 * aria-current="step", and every step says its state in words for a screen reader.
 * With `onSelect` the sections can be done in any order, so nothing is "done" or "not started": the current one is lit, every other one shows its number, and a screen
 * reader hears the section's name and its place (「第 N 节，共 M 节」), never 「已完成」 or 「未开始」 (a visited section is not a filled-in one; that would need a rule per section).
 * Without `onSelect` (a linear flow: the Telegram binding, the revise drawer) steps before the current one are done, as always.
 */
export function Stepper({ steps, current, waiting = false, label, className, onSelect, marked }: { steps: ReadonlyArray<Step>; current: number; waiting?: boolean; label?: string; className?: string;
  /** Given, every step is a button that goes to it (a form whose sections may be done in any order); `marked` lists the step ids that need a look (an error mark on the number). */
  onSelect?: (index: number) => void; marked?: ReadonlyArray<string> }) {
  const { t, locale } = useLocale();
  const free = Boolean(onSelect);
  const place = (index: number) => (locale === "en-US" ? `Section ${index + 1} of ${steps.length}` : `第 ${index + 1} 节，共 ${steps.length} 节`);
  return <ol data-slot="stepper" aria-label={label} className={cn("m-0 flex list-none items-start gap-0 p-0", className)}>
    {steps.map((step, index) => {
      const state = free ? (index === current ? "current" : "free") : index < current ? "done" : index === current ? (waiting ? "waiting" : "current") : "todo";
      const mark = <span aria-hidden="true" className={cn("relative z-[1] grid size-6 place-items-center rounded-full border text-caption font-medium",
        state === "done" && "border-brand bg-brand text-background", (state === "current" || state === "waiting") && "border-brand bg-background text-brand ring-2 ring-brand/25", (state === "todo" || state === "free") && "border-line-strong bg-background text-muted-foreground",
        marked?.includes(step.id) && "border-danger text-danger ring-2 ring-danger/25")}>
        {state === "done" ? <Check className="size-3.5" strokeWidth={3} /> : state === "waiting" ? <LoaderCircle className="size-3.5 motion-safe:animate-spin" /> : index + 1}
      </span>;
      const words = <span className={cn("text-small leading-snug", state === "todo" || state === "free" ? "text-muted-foreground" : "text-ink", index === current && "font-medium")}>{step.label}</span>;
      return <li key={step.id} data-step={step.id} data-state={state} aria-current={index === current ? "step" : undefined} className="relative flex min-w-0 flex-1 flex-col items-center gap-1.5 px-1 text-center">
        {index > 0 && <span aria-hidden="true" className={cn("absolute top-3 right-1/2 left-[-50%] h-px", !free && index <= current ? "bg-brand" : "bg-line-strong")} />}
        {onSelect
          ? <button type="button" data-step-button={step.id} aria-label={typeof step.label === "string" ? `${index + 1} ${step.label}` : undefined} onClick={() => onSelect(index)} className="flex min-h-11 min-w-0 flex-col items-center gap-1.5 rounded-sm px-1 outline-none focus-visible:ring-2 focus-visible:ring-ring">{mark}{" "}{words}</button>
          : <>{mark}{words}</>}
        <span className="sr-only">{free ? place(index) : state === "done" ? t("已完成") : state === "waiting" ? t("等待中") : state === "current" ? t("当前步骤") : t("未开始")}{marked?.includes(step.id) ? `${comma()}${t("这一步有要改的地方")}` : ""}</span>
      </li>;
    })}
  </ol>;
}
