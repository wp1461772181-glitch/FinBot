import { ExternalLink } from "lucide-react";
import { ChevronRight } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import type { KnowledgeChunkDetail } from "../../../api/knowledge-docs";
import { useLocale } from "../../../i18n";
import { isDerivedText } from "./knowledge-form.mjs";

export type ChunkDetail = { document: { title: string; source_text: string; source_url: string | null; status: string }; chunks: KnowledgeChunkDetail[] };

/**
 * 材料与文本块 (design 4.11): one document's saved text and its chunks, in a side drawer; Esc closes it and the focus goes back to the row that opened it.  The text is labelled for what it is: 保存的原文, or — when it starts with
 * the marker of a model analysis — 分析文本（含 AI 派生内容） (a provenance label, not a warning).  Each chunk says its place (the number, the section or 正文) and the status the server gave, as it gave it.
 */
export function ChunksDrawer({ open, onOpenChange, title, detail, error, loading, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void;
  title: string; detail: ChunkDetail | null; error: unknown; loading: boolean; returnFocus: () => void;
}) {
  const { t } = useLocale();
  const derived = detail ? isDerivedText(detail.document.source_text) : false;
  return <Drawer open={open} onOpenChange={onOpenChange} direction="right" autoFocus>
    <DrawerContent data-testid="knowledge-drawer" aria-describedby="knowledge-drawer-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus(); }}
      className="data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-xl">
      <DrawerHeader className="gap-1.5 border-b border-line">
        <DrawerTitle className="text-title-s [overflow-wrap:anywhere]">{detail?.document.title ?? title}</DrawerTitle>
        <DrawerDescription id="knowledge-drawer-description">{t("材料与文本块")}</DrawerDescription>
        {detail?.document.source_url && <a data-testid="knowledge-source-link" href={detail.document.source_url} target="_blank" rel="noreferrer" className="inline-flex w-fit items-center gap-1 rounded-sm text-small text-brand outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{t("打开原始来源")}<ExternalLink aria-hidden="true" className="size-3.5" /></a>}
      </DrawerHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        {error != null && <ErrorBar error={error} />}
        {loading && !detail && <DelayedSkeleton><div role="status" aria-busy="true"><span className="sr-only">{t("正在读取")}</span><SkeletonRows rows={4} /></div></DelayedSkeleton>}
        {detail && <>
          <Collapsible className="rounded-md border border-line bg-surface" data-testid="knowledge-source-text" data-derived={derived ? "true" : "false"}>
            <CollapsibleTrigger className="group/fold flex min-h-11 w-full items-center gap-2 rounded-md px-3 text-left text-body text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />
              <span data-testid="knowledge-source-label">{t(derived ? "分析文本（含 AI 派生内容）" : "保存的原文")}</span>
            </CollapsibleTrigger>
            <CollapsibleContent><pre className="material-fact m-3 whitespace-pre-wrap break-words px-3 py-2 font-quote text-small text-ink">{detail.document.source_text}</pre></CollapsibleContent>
          </Collapsible>
          <section aria-label={t("文本块")} className="flex min-w-0 flex-col gap-2">
            <h3 className="text-body font-medium text-ink">{t("文本块")} · {detail.chunks.length}</h3>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">{detail.chunks.map(chunk => <li key={chunk.id} data-testid="knowledge-chunk" className="flex min-w-0 flex-col gap-1 rounded-md border border-line bg-surface p-3">
              <p className="m-0 flex flex-wrap items-center gap-2 text-caption text-muted-foreground"><span className="font-mono">{chunk.ordinal + 1}</span><span>·</span><span>{chunk.section || t("正文")}</span><span>·</span><StatusBadge kind="neutral" className="h-5">{chunk.status}</StatusBadge></p>
              <p className="m-0 text-small text-ink [overflow-wrap:anywhere]">{chunk.answer}</p>
            </li>)}</ul>
          </section>
        </>}
      </div>
    </DrawerContent>
  </Drawer>;
}
