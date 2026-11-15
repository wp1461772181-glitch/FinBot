// A row of choices where exactly one is picked (native radios, so the arrow keys, Tab and screen readers work as they do everywhere): used by the
// animation level, the personality pickers and the rehearsal's controls.  Radios are visually hidden; the label is the button.  Clicking the
// choice that is already picked calls `onChange` too (a picked-by-default choice can be made the reader's own).
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> { value: T; label: ReactNode; hint?: ReactNode; disabled?: boolean }

export function Segmented<T extends string>({ name, legend, value, options, onChange, disabled, className, testid }: {
  name: string; legend: ReactNode; value: T | null; options: ReadonlyArray<SegmentedOption<T>>; onChange: (value: T) => void; disabled?: boolean; className?: string; testid?: string;
}) {
  return (
    <fieldset data-slot="segmented" data-testid={testid} disabled={disabled} className={cn("m-0 min-w-0 border-0 p-0", className)}>
      <legend className="mb-1.5 p-0 text-small font-medium text-ink">{legend}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <label key={option.value} data-option={option.value} className={cn(
            "relative inline-flex min-h-8 max-sm:min-h-11 cursor-pointer items-center rounded-sm border px-2.5 py-1 text-small leading-snug text-ink select-none",
            "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand",
            value === option.value ? "border-brand bg-brand-soft font-medium" : "border-line bg-surface hover:bg-sunken",
            (disabled || option.disabled) && "cursor-not-allowed opacity-55 hover:bg-surface",
          )}>
            <input type="radio" name={name} value={option.value} checked={value === option.value} disabled={disabled || option.disabled}
              onChange={() => onChange(option.value)} onClick={() => onChange(option.value)} className="sr-only" />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
