import { forecastCopy } from "../forecast-model.mjs";
import { useLocale } from "../i18n";
import { fitsInside, probabilityModel, probabilityText, type ProbabilitySegment, type ProbabilityTone } from "../probability-bar.mjs";
import { cn } from "@/lib/utils";

// The segment colours: down and up are the market tokens (they swap under 红涨绿跌), flat is the muted grey.  Text on a segment is the on-accent ink.
const TONE_BG: Record<ProbabilityTone, string> = { down: "bg-down", muted: "bg-muted-foreground", up: "bg-up" };

type Props = {
  probabilities: Partial<Record<"bearish" | "neutral" | "bullish", number>> | null | undefined;
  /** The version's model status: with no probabilities the bar says what the model was (a research-only version, an early one), not an empty track. */
  status?: string | null;
  /** `mini`: one line in a row, numbers on hover or focus.  `standard`: a card, numbers in the bar where they fit and in the legend. */
  size?: "mini" | "standard";
  /** The mini bar is a stop of the keyboard (its numbers show on focus); a row that already has its own stops turns it off, and shows them while any of the row has the focus. */
  focusable?: boolean;
  className?: string;
};

/**
 * The three-class probability bar (design 5.3): one drawing wherever a probability appears.  Down, flat, up in that order and those
 * colours; the widths and numbers are the data's, never rescaled to 100.  The track is an image to a screen reader and says all
 * three numbers in one sentence.  With no probabilities it shows the model's status in words instead of an empty bar.
 */
export function ProbabilityBar({ probabilities, status, size = "standard", focusable, className }: Props) {
  const { t, locale } = useLocale();
  const model = probabilityModel(probabilities);
  if (!model) {
    const words = status ? t(forecastCopy({ model_status: status }).statusName) : t("暂无概率");
    return <p data-slot="probability-bar" data-state="none" data-size={size} className={cn("text-small text-muted-foreground", className)}>{words}</p>;
  }
  const comma = locale === "en-US" ? ", " : "，";
  const sentence = probabilityText(model, t, comma);
  const mini = size === "mini";
  return <div data-slot="probability-bar" data-state="ready" data-size={size} className={cn("group relative min-w-0", className)}>
    <div role="img" aria-label={sentence} tabIndex={mini && focusable !== false ? 0 : undefined} data-slot="probability-track"
      className={cn("flex w-full overflow-hidden rounded-full bg-sunken outline-none ring-1 ring-line focus-visible:ring-2 focus-visible:ring-ring", mini ? "h-2.5" : "h-6")}>
      {model.segments.map((segment: ProbabilitySegment) => <span key={segment.key} data-segment={segment.key} data-tone={segment.tone} style={{ width: `${segment.width}%` }}
        className={cn("flex flex-none items-center justify-center overflow-hidden font-mono text-caption tabular-nums text-primary-foreground", TONE_BG[segment.tone])}>
        {!mini && fitsInside(segment) && <span aria-hidden="true">{segment.percent}%</span>}
      </span>)}
    </div>
    {mini
      ? <span aria-hidden="true" data-slot="probability-tip" className="pointer-events-none absolute left-0 top-full z-content mt-1 hidden whitespace-nowrap rounded-sm border border-line bg-surface px-2 py-1 font-mono text-caption text-ink shadow-pop group-focus-within:block group-hover:block group-focus-within/row:block">
        {model.segments.map((segment: ProbabilitySegment) => `${t(segment.phrase)} ${segment.percent}%`).join(" · ")}
      </span>
      : <ul aria-hidden="true" data-slot="probability-legend" className="m-0 mt-2 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-small text-ink-2">
        {model.segments.map((segment: ProbabilitySegment) => <li key={segment.key} className="flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-sm", TONE_BG[segment.tone])} />{t(segment.phrase)}<span className="font-mono tabular-nums text-ink">{segment.percent}%</span>
        </li>)}
        {!model.sumsToWhole && <li className="flex items-center gap-1.5 text-muted-foreground">{t("合计")}<span className="font-mono tabular-nums">{Math.round(model.sum)}%</span></li>}
      </ul>}
  </div>;
}
