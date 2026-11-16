import type { ReactNode } from "react";
import { OPINION_DISCLAIMER } from "../data-display.mjs";
import { useLocale } from "../i18n";
import { cn } from "@/lib/utils";

/**
 * The opinion material (design 2.2), the one implementation: a surface card with a thin opinion outline, a label that says whose words these are
 * (「模型意见 · 模型名 · 时间 / 版本」, a source tag and not a warning), a body, nested fact blocks for what the opinion cites, and a footnote.
 * The disclaimer sentence is the footnote of one card per page area: pass `disclaimer` on that card only.  The label's model, time and version
 * are values the version recorded; a missing one is left out, never guessed.
 */
export function OpinionCard({ model, time, version, disclaimer = false, footnote, children, className, ...rest }: {
  model?: string | null;
  time?: string | null;
  version?: string | null;
  /** Put the fixed disclaimer sentence in the footnote slot. */
  disclaimer?: boolean;
  /** Anything else for the footnote slot (shown above the disclaimer when both are given). */
  footnote?: ReactNode;
  children?: ReactNode;
  className?: string;
} & Omit<React.HTMLAttributes<HTMLElement>, "children" | "className">) {
  const { t } = useLocale();
  const parts = [t("模型意见"), model, version, time].filter((part): part is string => Boolean(part));
  return <section data-slot="opinion-card" className={cn("material-opinion flex min-w-0 flex-col gap-3 p-4", className)} {...rest}>
    <p data-slot="opinion-label" className="material-opinion-label w-fit py-0.5">{parts.join(" · ")}</p>
    <div data-slot="opinion-body" className="flex min-w-0 flex-col gap-3">{children}</div>
    {(footnote || disclaimer) && <div data-slot="opinion-footnote" className="material-opinion-footnote flex flex-col gap-1">
      {footnote}
      {disclaimer && <p data-slot="opinion-disclaimer">{t(OPINION_DISCLAIMER)}</p>}
    </div>}
  </section>;
}

/** A fact the opinion cites, as the fact material nested in the card (sunken, colourless, a rule on the left): the model's words never go in one. */
export function OpinionFacts({ children, className }: { children: ReactNode; className?: string }) {
  return <div data-slot="opinion-facts" className={cn("material-fact flex min-w-0 flex-col gap-1 px-3 py-2 text-small", className)}>{children}</div>;
}
