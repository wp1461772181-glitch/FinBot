import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/state/EmptyState";
import { cn } from "@/lib/utils";
import type { KnowledgeDocumentSummary } from "../../../api/knowledge-docs";
import { useLocale } from "../../../i18n";

/** The columns of the documents table (from a desktop's width); below `xl` the same cells are a card, two to a line. */
const COLUMNS = "xl:grid-cols-[minmax(11rem,2.4fr)_minmax(4rem,0.7fr)_minmax(4.5rem,0.8fr)_minmax(6.5rem,0.9fr)_minmax(3.5rem,0.6fr)_minmax(11rem,1.6fr)_minmax(4.5rem,0.8fr)_minmax(9rem,1.1fr)]";
const Label = ({ children }: { children: ReactNode }) => <span className="text-caption text-muted-foreground xl:hidden">{children}</span>;
function Cell({ label, children, className, mono }: { label: ReactNode; children: ReactNode; className?: string; mono?: boolean }) {
  return <div role="cell" className={cn("flex min-w-0 flex-col gap-0.5", className)}><Label>{label}</Label><span className={cn("min-w-0 text-small text-ink [overflow-wrap:anywhere]", mono && "font-mono")}>{children}</span></div>;
}

/**
 * 文档 (design 4.11): the documents in the library as a table on a desktop and cards below it (the same cells either way).  A document's title opens its chunks.  Its status is shown as the server gave it — nothing here says
 * a document is searchable or in effect.  重试 queues it for indexing again; 撤回 withdraws it (not available once it has been withdrawn).
 */
export function DocsList({ docs, busy, onOpen, onRetry, onWithdraw }: {
  docs: KnowledgeDocumentSummary[]; busy: boolean;
  onOpen: (doc: KnowledgeDocumentSummary, opener: HTMLElement) => void; onRetry: (doc: KnowledgeDocumentSummary) => void; onWithdraw: (doc: KnowledgeDocumentSummary) => void;
}) {
  const { t } = useLocale();
  if (!docs.length) return <div data-testid="knowledge-docs-empty" className="rounded-md border border-line"><EmptyState title={t("还没有已导入文档。可以先从上方选择已有材料。")} /></div>;
  const head = "text-caption text-muted-foreground";
  return <div role="table" aria-label={t("文档")} data-testid="knowledge-docs" className="flex min-w-0 flex-col xl:rounded-md xl:border xl:border-line">
    <div role="rowgroup" className="hidden xl:block"><div role="row" className={cn("grid items-center gap-x-4 border-b border-line px-3 py-2", COLUMNS)}>
      <span role="columnheader" className={head}>{t("标题")}</span><span role="columnheader" className={head}>{t("代码")}</span><span role="columnheader" className={head}>{t("来源类型")}</span><span role="columnheader" className={head}>{t("状态")}</span>
      <span role="columnheader" className={head}>{t("块数")}</span><span role="columnheader" className={head}>{t("观察时间")}</span><span role="columnheader" className={head}>{t("归属范围")}</span><span role="columnheader" className={head} />
    </div></div>
    <div className="flex flex-col gap-3 xl:gap-0">{docs.map(doc => <div key={doc.id} role="rowgroup" data-testid="knowledge-doc" data-doc={doc.id} data-active={doc.active ? "true" : "false"}
      className="rounded-md border border-line bg-surface xl:rounded-none xl:border-0 xl:border-b xl:bg-transparent xl:last:border-b-0">
      <div role="row" className={cn("grid grid-cols-2 items-start gap-x-3 gap-y-2 p-3 xl:items-center xl:gap-x-4", COLUMNS)}>
        <div role="cell" className="col-span-2 min-w-0 xl:col-span-1">
          <button type="button" data-testid="knowledge-doc-open" aria-label={`${t("打开文本块")} · ${doc.title}`} onClick={event => onOpen(doc, event.currentTarget)}
            className="-mx-1 min-h-8 rounded-sm px-1 text-left text-body font-medium text-ink outline-none [overflow-wrap:anywhere] hover:underline focus-visible:ring-2 focus-visible:ring-ring max-xl:min-h-11">{doc.title}</button>
        </div>
        <Cell label={t("代码")} mono>{doc.symbol || "FAQ"}</Cell>
        <Cell label={t("来源类型")}>{doc.source_type}</Cell>
        <Cell label={t("状态")} className="items-start"><span data-testid="knowledge-doc-status"><StatusBadge kind="neutral" className="h-5">{doc.status}</StatusBadge></span></Cell>
        <Cell label={t("块数")} mono>{doc.chunks} {t("块")}</Cell>
        <Cell label={t("观察时间")} mono>{doc.observed_at || <span className="font-sans text-muted-foreground">{t("观察时间未知")}</span>}</Cell>
        <Cell label={t("归属范围")}>{doc.owner_scope}</Cell>
        <div role="cell" className="col-span-2 flex items-center gap-2 xl:col-span-1 xl:justify-end">
          <Button type="button" size="sm" variant="outline" data-testid="knowledge-retry" disabled={busy} aria-label={`${t("重试")} · ${doc.title}`} className="max-xl:h-11" onClick={() => onRetry(doc)}>{t("重试")}</Button>
          <Button type="button" size="sm" variant="outline" data-testid="knowledge-withdraw" disabled={busy || !doc.active} aria-label={`${t("撤回")} · ${doc.title}`} className="max-xl:h-11" onClick={() => onWithdraw(doc)}>{t("撤回")}</Button>
        </div>
      </div>
    </div>)}</div>
  </div>;
}

export type Candidate = { id: string; question: string; answer: string; category: string; evidence_quote: string };

/** 待审核候选: each a card with the question, the answer, the quote it rests on (the fact material) and the two ways to answer it. */
export function Candidates({ candidates, busy, onReview }: { candidates: Candidate[]; busy: boolean; onReview: (candidate: Candidate, approved: boolean) => void }) {
  const { t } = useLocale();
  if (!candidates.length) return <div data-testid="knowledge-candidates-empty" className="rounded-md border border-line"><EmptyState title={t("没有待审核条目。")} /></div>;
  return <ul data-testid="knowledge-candidates" className="m-0 grid list-none gap-3 p-0 md:grid-cols-2">{candidates.map(candidate => <li key={candidate.id} data-testid="knowledge-candidate" data-candidate={candidate.id} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3.5">
    <strong className="text-body font-medium text-ink [overflow-wrap:anywhere]">{candidate.question}</strong>
    <p className="m-0 text-small text-ink-2 [overflow-wrap:anywhere]">{candidate.answer}</p>
    <blockquote className="material-fact m-0 px-3 py-2 font-quote text-small text-ink">{candidate.evidence_quote}</blockquote>
    <div className="mt-auto flex items-center justify-end gap-2 pt-1">
      <Button type="button" size="sm" variant="outline" data-testid="knowledge-reject" disabled={busy} aria-label={`${t("拒绝")} · ${candidate.question}`} className="max-sm:h-11" onClick={() => onReview(candidate, false)}>{t("拒绝")}</Button>
      <Button type="button" size="sm" data-testid="knowledge-approve" disabled={busy} aria-label={`${t("审核并排队索引")} · ${candidate.question}`} className="max-sm:h-11" onClick={() => onReview(candidate, true)}>{t("审核并排队索引")}</Button>
    </div>
  </li>)}</ul>;
}
