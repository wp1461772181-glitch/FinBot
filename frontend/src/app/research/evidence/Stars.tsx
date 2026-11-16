import { Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale } from "../../../i18n";
import { clampStars } from "./evidence-model.mjs";

/** The reader's own credibility stars, read only: filled stars up to the value, outlines after.  The text says it in words too. */
export function StarsReadout({ value, className }: { value: number; className?: string }) {
  const { t } = useLocale();
  const stars = clampStars(value);
  return <span data-slot="stars" data-stars={stars} role="img" aria-label={`${t("用户可信度")} ${value}/5`} className={cn("inline-flex items-center gap-0.5", className)}>
    {[1, 2, 3, 4, 5].map(n => <Star key={n} aria-hidden="true" className={cn("size-3.5", n <= stars ? "fill-current text-ink" : "text-line-strong")} />)}
    <span aria-hidden="true" className="ml-1 font-mono text-caption text-muted-foreground">{value}/5</span>
  </span>;
}
