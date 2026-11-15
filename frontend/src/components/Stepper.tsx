// A short row of steps (design 5.4): which are done, which one is current, whether the current one is waiting for something outside the page.  Used by the
// Telegram binding (save the token → make a code → wait for the message); the other multi-step forms of the redesign reuse it.
import type { ReactNode } from "react";
import { Check, LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale } from "../i18n";

export type Step = { id: string; label: ReactNode };

/**
 * `current` is the index of the step being done; a number equal to the step count means all are done.  `waiting` marks the current step as one that
 * finishes on its own (the page is polling for it): it shows a turning mark instead of its number.  The list is an `<ol>`; the current step has
 * aria-current="step", and every step says its state in words for a screen reader.
 */
export function Stepper({ steps, current, waiting = false, label, className }: { steps: ReadonlyArray<Step>; current: number; waiting?: boolean; label?: string; className?: string }) {
  const { t } = useLocale();
  return <ol data-slot="stepper" aria-label={label} className={cn("m-0 flex list-none items-start gap-0 p-0", className)}>
    {steps.map((step, index) => {
      const state = index < current ? "done" : index === current ? (waiting ? "waiting" : "current") : "todo";
      return <li key={step.id} data-step={step.id} data-state={state} aria-current={index === current ? "step" : undefined} className="relative flex min-w-0 flex-1 flex-col items-center gap-1.5 px-1 text-center">
        {index > 0 && <span aria-hidden="true" className={cn("absolute top-3 right-1/2 left-[-50%] h-px", index <= current ? "bg-brand" : "bg-line-strong")} />}
        <span aria-hidden="true" className={cn("relative z-[1] grid size-6 place-items-center rounded-full border text-caption font-medium",
          state === "done" && "border-brand bg-brand text-background", (state === "current" || state === "waiting") && "border-brand bg-background text-brand ring-2 ring-brand/25", state === "todo" && "border-line-strong bg-background text-muted-foreground")}>
          {state === "done" ? <Check className="size-3.5" strokeWidth={3} /> : state === "waiting" ? <LoaderCircle className="size-3.5 motion-safe:animate-spin" /> : index + 1}
        </span>
        <span className={cn("text-small leading-snug", state === "todo" ? "text-muted-foreground" : "text-ink", index === current && "font-medium")}>{step.label}</span>
        <span className="sr-only">{state === "done" ? t("已完成") : state === "waiting" ? t("等待中") : state === "current" ? t("当前步骤") : t("未开始")}</span>
      </li>;
    })}
  </ol>;
}
