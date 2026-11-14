import type { HTMLAttributes, ReactNode, Ref } from "react";
import { Link } from "react-router";
import { ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

/** A verbatim quote: the serif face says "these are the source's words" (design 2.2).  The model's own words never go in one. */
export function SourceQuote({ children, className }: { children: ReactNode; className?: string }) {
  return <blockquote data-slot="source-quote" className={cn("m-0 whitespace-pre-wrap break-words font-quote text-small text-ink", className)}>{children}</blockquote>;
}

type Props = Omit<HTMLAttributes<HTMLElement>, "title"> & {
  /** The source's number in the answer, the 序号 drawn at the card's top right. */
  ordinal: number | string;
  title: string;
  section?: string;
  /** The kind of source, already translated (「已保存申报」). */
  type?: string;
  /** Provenance of derived content (a saved AI analysis), already translated.  A statement of where it comes from, not a warning. */
  derived?: string;
  /** Short facts under the title (dates, version), already translated, shown in the monospace face. */
  meta?: string[];
  /** A note on the stored content (「保存内容可能不完整」). */
  note?: string;
  /** The excerpt region: a SourceQuote, a skeleton, an error bar. */
  children?: ReactNode;
  /** The original: an external page (new tab) or a page of this app. */
  href?: string | null;
  to?: string | null;
  openLabel: string;
  highlighted?: boolean;
  cardRef?: Ref<HTMLElement>;
};

const open = "inline-flex h-8 items-center gap-1.5 rounded-sm px-2 text-small font-medium text-brand outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring";

/**
 * One source of an answer, in the fact material (design 2.2): sunken, colourless, a rule on the left, the number at the top right,
 * the excerpt in the quote face.  The chat's 来源 tab uses it; the forecast brief and the evidence page reuse it (P6).
 */
export function SourceCard({ ordinal, title, section, type, derived, meta = [], note, children, href, to, openLabel, highlighted, cardRef, className, ...rest }: Props) {
  return <article data-slot="source-card" data-ordinal={ordinal} data-highlight={highlighted ? "" : undefined} ref={cardRef} tabIndex={-1}
    className={cn("material-fact flex min-w-0 flex-col gap-2 py-3 pl-3 pr-12", className)} {...rest}>
    <span className="material-fact-source" aria-label={`[${ordinal}]`}>[{ordinal}]</span>
    <div className="flex min-w-0 flex-col gap-1">
      <h3 data-slot="source-card-title" className="text-body font-medium text-ink [overflow-wrap:anywhere]">{title}</h3>
      {section && <p className="text-caption text-muted-foreground [overflow-wrap:anywhere]">{section}</p>}
      {(type || derived) && <p className="flex flex-wrap items-center gap-1.5 text-caption text-muted-foreground">
        {type && <span data-slot="source-card-type">{type}</span>}
        {derived && <span data-slot="source-card-derived" className="rounded-sm border border-line-strong px-1.5 text-ink-2">{derived}</span>}
      </p>}
      {meta.length > 0 && <p data-slot="source-card-meta" className="flex flex-wrap gap-x-3 font-mono text-caption text-muted-foreground">{meta.map((item) => <span key={item}>{item}</span>)}</p>}
      {note && <p className="text-caption text-muted-foreground">{note}</p>}
    </div>
    {children}
    {(href || to) && <div className="-ml-2">
      {href ? <a href={href} target="_blank" rel="noopener noreferrer" data-slot="source-card-open" className={open}>{openLabel}<ExternalLink aria-hidden="true" className="size-3.5" /></a>
        : <Link to={to!} data-slot="source-card-open" className={open}>{openLabel}</Link>}
    </div>}
  </article>;
}
