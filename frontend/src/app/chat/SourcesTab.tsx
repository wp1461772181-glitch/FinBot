import { useEffect, useRef, useState } from "react";
import { SourceCard, SourceQuote } from "@/components/SourceCard";
import { Skeleton } from "@/components/state/Skeleton";
import { ErrorBar } from "@/components/state/ErrorBar";
import { errorReason } from "@/components/state/error-message";
import { ApiError } from "../../api/base";
import { type AgentChatMessage, type AgentCitation } from "../../api/conversations";
import { citationOrdinal } from "../../chat-citations.mjs";
import { useLocale } from "../../i18n";
import { roundSources, turnKey } from "../../panel-model.mjs";
import { derivedDetail, excerptSource, isDerived, originalHref, sourceDates, sourceTypeLabel } from "../../source-view.mjs";
import { useCitationDetail } from "./citation-details";
import { usePanel } from "./panel-context";

/** One source of the round, with its excerpt: the stored quote, or the chunk read through the knowledge API (a skeleton while it comes, an error bar with 重试 when it does not). */
function Source({ citation, ordinal, marked, cardRef, onEscape }: { citation: AgentCitation; ordinal: number; marked: boolean; cardRef: (el: HTMLElement | null) => void; onEscape: () => void }) {
  const { t } = useLocale();
  const from = excerptSource(citation);
  const { detail, reload } = useCitationDetail(citation.chunk_id, from === "chunk");
  const ready = detail?.status === "ready" ? detail.value : null;
  const dates = sourceDates(citation);
  const meta: string[] = [];
  if (dates.web) {
    meta.push(dates.published ? `${t("发布")} ${dates.published}` : t("发布日期未知"));
    meta.push(dates.observed ? `${t("抓取")} ${dates.observed}` : `${t("抓取")} ${t("时间未知")}`);
  } else {
    if (dates.published) meta.push(`${t("发布")} ${dates.published}`);
    meta.push(dates.observed ? `${t("观察")} ${dates.observed}` : t("观察时间未知"));
  }
  const version = derivedDetail(ready);
  if (version) meta.push(version);

  let excerpt = null;
  if (from === "unavailable") excerpt = <p className="text-small text-muted-foreground">{t("来源已撤回或不可访问")}</p>;
  else if (from === "quote") excerpt = <SourceQuote>{citation.quote}</SourceQuote>;
  else if (from === "chunk") {
    if (!detail || detail.status === "loading") excerpt = <div role="status" aria-busy="true" data-testid="excerpt-loading" className="flex flex-col gap-1.5"><span className="sr-only">{t("正在读取")}</span><Skeleton className="h-3.5 w-full" /><Skeleton className="h-3.5 w-11/12" /><Skeleton className="h-3.5 w-3/5" /></div>;
    else if (detail.status === "failed") {
      const gone = detail.error instanceof ApiError && (detail.error.status === 404 || detail.error.status === 410);
      excerpt = <div data-testid="excerpt-error"><ErrorBar message={gone ? t("来源已撤回或不可访问") : errorReason(detail.error, t)} onRetry={reload} /></div>;
    } else {
      const quotes = ready?.original_quotes ?? [];
      excerpt = <>
        {ready?.excerpt ? <SourceQuote>{ready.excerpt}</SourceQuote> : <p className="text-small text-muted-foreground">{t("来源已撤回或不可访问")}</p>}
        {quotes.length > 0 && <div className="flex flex-col gap-1.5"><p className="text-caption font-medium text-muted-foreground">{t("原文引文：")}</p>
          {quotes.map((quote, index) => <SourceQuote key={index} className="border-l border-line-strong pl-2">{quote}</SourceQuote>)}</div>}
      </>;
    }
  }
  return <SourceCard cardRef={cardRef} data-testid="source-card" highlighted={marked} ordinal={ordinal} title={citation.title} section={citation.section || undefined}
    type={t(sourceTypeLabel(citation.source_type))} derived={isDerived(citation, ready) ? t("派生") : undefined} meta={meta}
    note={citation.truncated ? t("保存内容可能不完整") : undefined} href={originalHref(citation, ready)} openLabel={t("打开原文")}
    onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); onEscape(); } }}>
    {excerpt}
  </SourceCard>;
}

/**
 * The 来源 tab: every source of the round the panel shows, in the order the old 引用来源 drawer listed them.  A jump from a chip
 * scrolls to its card and marks it for a moment; when the jump came from the keyboard the focus goes into the card, and Esc takes it
 * back to the chip.
 */
export default function SourcesTab({ m, i }: { m: AgentChatMessage; i: number }) {
  const { t } = useLocale(), panel = usePanel();
  const list = roundSources(m), all = Array.isArray(m.citations) ? m.citations : [];
  const cards = useRef(new Map<number, HTMLElement>());
  const [marked, setMarked] = useState<number | null>(null);
  const key = turnKey(m, i), focus = panel.focus;
  useEffect(() => {
    if (!focus || focus.nonce === panel.handledFocus.current || (focus.key !== null && focus.key !== key)) return;
    panel.handledFocus.current = focus.nonce;
    const card = focus.ordinal === null ? undefined : cards.current.get(focus.ordinal);
    if (!card) return;
    card.scrollIntoView({ block: "center", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    setMarked(focus.ordinal);
    if (focus.byKeyboard) card.focus({ preventScroll: true });
    const timer = window.setTimeout(() => setMarked(null), 1800);
    return () => window.clearTimeout(timer);
  }, [focus, key, panel.handledFocus]);
  if (list.length === 0) return <p data-testid="sources-empty" className="px-1 py-6 text-small text-muted-foreground">{t("这一轮没有引用来源。")}</p>;
  return <div data-testid="sources-list" className="flex flex-col gap-3">
    <h2 className="text-caption font-medium text-muted-foreground">{t("引用来源")} · {t("本轮")} {list.length} {t("条")}</h2>
    {list.map((citation, j) => {
      const ordinal = citationOrdinal(citation, all.indexOf(citation) >= 0 ? all.indexOf(citation) : j);
      return <Source key={citation.chunk_id ?? citation.source_url ?? ordinal} citation={citation} ordinal={ordinal} marked={marked === ordinal}
        cardRef={(el) => { if (el) cards.current.set(ordinal, el); else cards.current.delete(ordinal); }} onEscape={() => panel.returnToOrigin()} />;
    })}
  </div>;
}
