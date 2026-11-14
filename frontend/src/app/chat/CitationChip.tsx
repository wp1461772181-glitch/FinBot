import { useRef, useState, type ReactNode } from "react";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Skeleton } from "@/components/state/Skeleton";
import { SourceQuote } from "@/components/SourceCard";
import type { AgentCitation } from "../../api";
import { useLocale } from "../../i18n";
import { excerptSource } from "../../source-view.mjs";
import { useCitationDetail } from "./citation-details";
import { usePanel } from "./panel-context";

/** What the hover card says of a source: its name and the start of its excerpt.  The excerpt of a stored chunk is read when the card opens. */
function Preview({ citation }: { citation: AgentCitation }) {
  const { t } = useLocale();
  const from = excerptSource(citation);
  const { detail } = useCitationDetail(citation.chunk_id, from === "chunk");
  let body: ReactNode = null;
  if (from === "quote") body = <SourceQuote className="line-clamp-4">{citation.quote}</SourceQuote>;
  else if (from === "unavailable") body = <p className="text-small text-muted-foreground">{t("来源已撤回或不可访问")}</p>;
  else if (from === "chunk") {
    if (!detail || detail.status === "loading") body = <div role="status" aria-busy="true" className="flex flex-col gap-1.5"><span className="sr-only">{t("正在读取")}</span><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-4/5" /></div>;
    else if (detail.status === "ready") body = detail.value.excerpt ? <SourceQuote className="line-clamp-4">{detail.value.excerpt}</SourceQuote> : <p className="text-small text-muted-foreground">{t("来源已撤回或不可访问")}</p>;
    else body = <p className="text-small text-muted-foreground">{t("摘录读取失败，在右侧来源里可以重试。")}</p>;
  } else if (citation.quote) body = <SourceQuote className="line-clamp-4">{citation.quote}</SourceQuote>;
  return <div className="flex flex-col gap-2">
    <p className="text-small font-medium text-ink [overflow-wrap:anywhere]">{citation.title}{citation.section ? ` · ${citation.section}` : ""}</p>
    {body}
  </div>;
}

/**
 * The [n] in an answer: a small chip.  Hover or keyboard focus shows the start of the excerpt; a click (or Enter) finds the source in
 * the right panel's 来源 tab and marks it.  The chip is a button, not a link: it goes to a place in this page, never away from it.
 */
export function CitationChip({ citation, ordinal, turnKey, children }: { citation: AgentCitation; ordinal: number; turnKey: string; children?: ReactNode }) {
  const { t } = useLocale(), panel = usePanel();
  // A click puts the card away.  The press has also focused the chip, and the card's own focus timer would open it again under the pointer.
  const [peek, setPeek] = useState(false), quietUntil = useRef(0);
  const label = `${t("引用来源")} ${ordinal} · ${citation.title}`;
  return <HoverCard open={peek} onOpenChange={(next) => { if (next && performance.now() < quietUntil.current) return; setPeek(next); }} openDelay={200} closeDelay={80}>
    <HoverCardTrigger asChild>
      <button type="button" data-testid="citation-chip" data-ordinal={ordinal} aria-label={label}
        className="mx-px inline-flex cursor-pointer items-center rounded-sm bg-sunken px-1 align-baseline font-mono text-caption leading-[1.35] text-ink-2 outline-none transition-colors duration-1 hover:bg-primary hover:text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring [&+&]:ml-1"
        onClick={(event) => { setPeek(false); quietUntil.current = performance.now() + 600; panel.showSource(turnKey, ordinal, event.currentTarget, event.detail === 0); }}>[{children ?? ordinal}]</button>
    </HoverCardTrigger>
    <HoverCardContent side="top" align="start" className="w-80 max-w-[calc(100vw-2rem)] p-3"><Preview citation={citation} /></HoverCardContent>
  </HoverCard>;
}
