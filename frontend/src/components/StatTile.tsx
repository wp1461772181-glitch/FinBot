import type { ReactNode } from "react";
import type { DeltaDirection } from "../delta.mjs";
import { cn } from "@/lib/utils";

const TONE: Record<DeltaDirection, string> = { up: "text-up", down: "text-down", flat: "text-muted-foreground" };
// The three arrows are drawn here (the same strokes as lucide's ArrowUp / ArrowDown / ArrowRight): importing lucide's would share those icon modules with the chat, whose chunk is on the first screen.
const ARROWS: Record<DeltaDirection, string[]> = { up: ["M12 19V5", "m5 12 7-7 7 7"], down: ["M12 5v14", "m19 12-7 7-7-7"], flat: ["M5 12h14", "m12 5 7 7-7 7"] };

/**
 * A signed change (design 2.3): an arrow and a sign always come with the colour, so the colour is never the only thing that says up or down.
 * `text` is the figure with its sign ("+3.20 (+1.30%)", see signedChange in data-display.mjs); the arrow is drawn here.
 */
export function Change({ direction, text, className }: { direction: DeltaDirection; text: string; className?: string }) {
  if (!text) return null;
  return <span data-slot="change" data-direction={direction} className={cn("inline-flex items-center gap-0.5 whitespace-nowrap font-mono tabular-nums", TONE[direction], className)}>
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="size-3.5 shrink-0">{ARROWS[direction].map(d => <path key={d} d={d} />)}</svg>{text}
  </span>;
}

/**
 * One key number (design 5.3): a label, the value in the monospace face, an optional change with its arrow and sign, and a footnote.  The four
 * slots are all there is; what goes in them is the caller's.
 */
export function StatTile({ label, value, change, footnote, className }: {
  label: ReactNode;
  value: ReactNode;
  change?: { direction: DeltaDirection; text: string } | null;
  footnote?: ReactNode;
  className?: string;
}) {
  return <div data-slot="stat-tile" className={cn("flex min-w-0 flex-col gap-1 rounded-md border border-line bg-surface p-3", className)}>
    <p data-slot="stat-label" className="text-caption text-muted-foreground">{label}</p>
    <p data-slot="stat-value" data-num className="font-mono text-title-m tabular-nums text-ink">{value}</p>
    {change && change.text && <p data-slot="stat-change" className="text-small"><Change direction={change.direction} text={change.text} /></p>}
    {footnote && <p data-slot="stat-footnote" className="text-caption text-muted-foreground">{footnote}</p>}
  </div>;
}
