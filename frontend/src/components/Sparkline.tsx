import { useLocale } from "../i18n";
import { sparklinePoints } from "../data-display.mjs";
import { cn } from "@/lib/utils";

/**
 * A line of the last closes, no axes (the same drawing as the workspace card's: the polyline stretched into its box, a hairline stroke that does not
 * thicken with the stretch).  It is a picture of the shape, not of a direction, so it takes the neutral chart colour and never the up / down colours.
 */
export function Sparkline({ closes, width = 160, height = 32, label, className }: { closes: number[]; width?: number; height?: number; label?: string; className?: string }) {
  const { t } = useLocale();
  const points = sparklinePoints(closes, width, height);
  if (!points) return null;
  return <svg data-slot="sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label ?? t("近 3 个月")}
    className={cn("block h-8 w-full text-chart-1", className)}>
    <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}
