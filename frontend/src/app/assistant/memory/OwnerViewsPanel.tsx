import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { listOwnerViews } from "../../../api/owner-views";
import { useLocale } from "../../../i18n";
import { dayLabel } from "../../../owner-views.mjs";
import { paths } from "../../../routes.mjs";
import { useLoad } from "../../use-load";

/**
 * 你的看法 (the memory page's section): the owner's active view of each company, with his words and the link to that company's page.  Nothing is written here; the owner says
 * his view in conversation and the model records it.  A view is not evidence.
 */
export function OwnerViewsPanel() {
  const { t, locale } = useLocale();
  const data = useLoad(signal => listOwnerViews(signal));
  const views = data.data;
  return <section data-testid="owner-views" aria-labelledby="owner-views-title" className="flex min-w-0 flex-col gap-2">
    <h2 id="owner-views-title" className="text-title-s text-ink">{t("你的看法")}{views && views.length > 0 && <span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{views.length}</span>}</h2>
    {data.error != null && <ErrorBar error={data.error} onRetry={() => void data.reload()} retrying={data.loading} />}
    {!views && data.loading && <DelayedSkeleton><div role="status" aria-busy="true" className="flex flex-col gap-2"><span className="sr-only">{t("正在读取")}</span>{[0, 1].map(i => <Skeleton key={i} className="h-20 w-full" />)}</div></DelayedSkeleton>}
    {views && views.length === 0 && <div data-testid="owner-views-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("还没有记下对哪家公司的看法。在对话里说出你的看法，它会记下来。")} /></div>}
    {views && views.length > 0 && <ul className="m-0 flex list-none flex-col gap-2 p-0">{views.map(view => <li key={view.id} data-testid="owner-view-item" data-symbol={view.symbol} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <span data-testid="owner-view-symbol" className="font-mono text-body font-medium text-ink">{view.symbol}</span>
        <span className="font-mono text-caption text-muted-foreground">{locale === "en-US" ? `${t("说的")} ${dayLabel(view.created_at, locale)}` : `${dayLabel(view.created_at, locale)} ${t("说的")}`}</span>
        <Link to={paths.company(view.symbol)} data-testid="owner-view-link" aria-label={`${t("打开公司页")} · ${view.symbol}`} className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-sm text-small text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring md:min-h-0">{t("打开公司页")}<ArrowRight aria-hidden="true" className="size-3.5" /></Link>
      </div>
      <p className="m-0 text-body text-ink [overflow-wrap:anywhere]">{view.text}</p>
      {view.quote.trim() && <blockquote data-testid="owner-view-quote" className="material-fact m-0 px-3 py-2 font-quote text-small text-ink">“{view.quote}”</blockquote>}
    </li>)}</ul>}
  </section>;
}
