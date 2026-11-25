import { ChevronRight } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { useLocale } from "../../../i18n";

/**
 * 它每轮实际读到的 (the 它眼中的你 tab): the profile text the default bot reads before each conversation turn, verbatim in a `<pre>` (no Markdown), cut line included.  Folded: it is long.
 * `text` null with no failure is an owner with no profile.  `failed`: the server could not build this part.
 */
export function SeenBlockFold({ text, failed, loading, onReload }: { text: string | null; failed: boolean; loading: boolean; onReload: () => Promise<void> }) {
  const { t } = useLocale();
  if (failed) return <section data-testid="memory-block" className="flex min-w-0 flex-col gap-2">
    <h2 className="text-title-s text-ink">{t("它每轮实际读到的")}</h2>
    <ErrorBar message={t("这一部分暂时读不出来。")} onRetry={() => void onReload()} retrying={loading} />
  </section>;
  if (text === null) return <section data-testid="memory-block" className="flex min-w-0 flex-col gap-2">
    <h2 className="text-title-s text-ink">{t("它每轮实际读到的")}</h2>
    {loading
      ? <DelayedSkeleton><div role="status" aria-busy="true"><span className="sr-only">{t("正在读取")}</span><Skeleton className="h-10 w-full" /></div></DelayedSkeleton>
      : <p data-testid="memory-block-empty" className="m-0 text-small text-muted-foreground">{t("现在没有画像，它每轮什么都不读。")}</p>}
  </section>;
  return <section data-testid="memory-block" className="flex min-w-0 flex-col gap-2">
    <Collapsible data-testid="memory-block-fold" className="rounded-md border border-line bg-surface">
      <CollapsibleTrigger className="group/fold flex min-h-11 w-full items-center gap-2 rounded-md px-3 text-left text-title-s text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />{t("它每轮实际读到的")}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex min-w-0 flex-col gap-2 border-t border-line p-3">
          <p data-testid="memory-block-note" className="m-0 text-small text-ink-2">{t("这是默认 bot「助理」每轮对话前读到的画像原文；条目多时会截断，截掉的仍在上面的列表里。")}</p>
          <pre data-testid="memory-block-text" className="m-0 min-w-0 whitespace-pre-wrap rounded-sm bg-sunken p-3 font-mono text-small text-ink [overflow-wrap:anywhere]">{text}</pre>
        </div>
      </CollapsibleContent>
    </Collapsible>
  </section>;
}
