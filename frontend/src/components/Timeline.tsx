import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type TimelineItem = {
  id: string;
  /** The first line: what happened (「v3 · 人工修订」). */
  title: ReactNode;
  /** A line of small facts under it (a date, a model). */
  meta?: ReactNode;
  /** Marks next to the title (a badge). */
  marks?: ReactNode;
  /** Anything else under the item (a note that belongs to this moment). */
  note?: ReactNode;
};

/**
 * A vertical timeline (design 5.3): one item per moment, a dot on a rule.  Written once for the forecast versions; the run records of a routine, the monitor
 * and the process list reuse it.  Give `onSelect` and every item is a button (the current one has aria-current); without it the items are plain text.
 * The items come in the order they are to be read: the caller decides which end is the newest.
 */
export function Timeline({ items, selectedId, onSelect, label, className }: {
  items: ReadonlyArray<TimelineItem>;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  label?: string;
  className?: string;
}) {
  return <ol data-slot="timeline" aria-label={label} className={cn("m-0 flex list-none flex-col p-0", className)}>
    {items.map((item, index) => {
      const selected = item.id === selectedId;
      const body = <>
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-small text-ink"><span className={cn("min-w-0", selected && "font-medium")}>{item.title}</span>{item.marks}</span>
        {item.meta && <span className="block min-w-0 text-caption text-muted-foreground [overflow-wrap:anywhere]">{item.meta}</span>}
      </>;
      return <li key={item.id} data-slot="timeline-item" data-id={item.id} data-selected={selected ? "" : undefined} className="relative flex min-w-0 gap-3 pb-4 last:pb-0">
        {index < items.length - 1 && <span aria-hidden="true" className="absolute top-4 bottom-0 left-[5px] w-px bg-line-strong" />}
        <span aria-hidden="true" className={cn("relative z-[1] mt-1 size-[11px] shrink-0 rounded-full border-2", selected ? "border-brand bg-brand" : "border-line-strong bg-background")} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {onSelect
            ? <button type="button" aria-current={selected ? "true" : undefined} onClick={() => onSelect(item.id)}
              className={cn("-mx-2 -my-1 flex min-w-0 flex-col gap-0.5 rounded-sm px-2 py-1 text-left outline-none hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring", selected && "bg-brand-soft")}>{body}</button>
            : <div className="flex min-w-0 flex-col gap-0.5">{body}</div>}
          {item.note}
        </div>
      </li>;
    })}
  </ol>;
}
