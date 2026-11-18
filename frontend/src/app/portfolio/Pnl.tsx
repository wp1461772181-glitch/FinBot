import { Change } from "@/components/StatTile";
import { cn } from "@/lib/utils";
import { pnlView } from "./portfolio-view.mjs";

/**
 * A profit-and-loss figure (design 2.3): a gain or a loss is the up / down colour with an arrow and a sign, all three, so the colour is never the only
 * thing that says which way it went.  A zero, or a figure the server did not give, is plain text: no colour, no arrow, no sign.  `data-pnl` names the
 * direction the figure was drawn in (the smoke check reads it).
 */
export function Pnl({ value, percent = false, className }: { value: string | null | undefined; percent?: boolean; className?: string }) {
  const view = pnlView(value, { percent });
  return <span data-pnl={view.direction} className="inline-flex">
    {view.signed
      ? <Change direction={view.direction as "up" | "down"} text={view.text} className={className} />
      : <span className={cn("font-mono tabular-nums whitespace-nowrap text-ink-2", className)}>{view.text}</span>}
  </span>;
}
