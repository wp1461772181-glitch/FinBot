import type { ReactNode } from "react";
import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import type { MemoryWatch } from "../../../api/memory-overview";
import { useLocale } from "../../../i18n";
import { watchRows } from "../../../memory-overview.mjs";
import { paths } from "../../../routes.mjs";
import { WatchRulesSection } from "./WatchRulesSection";

/** One of the three lists: its title, the link to the page where it is changed, and its rows (or 「（没有）」: an empty list is said, never left out). */
function WatchList({ id, title, linkLabel, to, empty, children }: { id: string; title: string; linkLabel: string; to: string; empty: boolean; children: ReactNode }) {
  const { t } = useLocale();
  return <div data-testid={`memory-watch-${id}`} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h3 className="text-small font-medium text-ink">{t(title)}</h3>
      <Link to={to} data-testid={`memory-watch-${id}-link`} className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-sm text-small text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring md:min-h-0">{t(linkLabel)}<ArrowRight aria-hidden="true" className="size-3.5" /></Link>
    </div>
    {empty ? <p data-testid={`memory-watch-${id}-empty`} className="m-0 text-small text-muted-foreground">{t("（没有）")}</p> : children}
  </div>;
}

/**
 * 它在帮你盯的 (the 它眼中的你 tab): what it watches for him.  The first three lists are read-only here (each is changed on its own page, with a link): his portfolio plans, his alert routines, the research queue.
 * Then the rules block (WatchRulesSection: his own rules, the system defaults he can switch off or re-threshold, the sensitivity), which he changes right here, and the server's note about the defaults.  `failed`: the server could not build this part.
 */
export function WatchPanel({ watch, failed, loading, onReload }: { watch: MemoryWatch | null; failed: boolean; loading: boolean; onReload: () => Promise<void> }) {
  const { t, locale } = useLocale();
  const rows = watch ? watchRows(watch, locale) : null;
  return <section data-testid="memory-watch" aria-labelledby="memory-watch-title" className="flex min-w-0 flex-col gap-2">
    <h2 id="memory-watch-title" className="text-title-s text-ink">{t("它在帮你盯的")}</h2>
    {failed && <ErrorBar message={t("这一部分暂时读不出来。")} onRetry={() => void onReload()} retrying={loading} />}
    {!rows && !failed && loading && <DelayedSkeleton><div role="status" aria-busy="true" className="flex flex-col gap-2"><span className="sr-only">{t("正在读取")}</span>{[0, 1].map(i => <Skeleton key={i} className="h-16 w-full" />)}</div></DelayedSkeleton>}
    {rows && <>
      <WatchList id="plans" title="持仓计划" linkLabel="去持仓页改" to={paths.portfolio()} empty={rows.plans.length === 0}>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">{rows.plans.map(plan => <li key={plan.symbol} data-testid="memory-watch-plan" data-symbol={plan.symbol} className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-small text-ink-2">
          <span className="font-mono text-body font-medium text-ink">{plan.symbol}</span>
          {plan.prices.map(price => <span key={price.key} data-testid="memory-watch-price">{t(price.label)} <span className="font-mono text-ink">{price.value}</span></span>)}
          {plan.text && <span className="min-w-0 [overflow-wrap:anywhere]">{plan.text}</span>}
        </li>)}</ul>
      </WatchList>
      <WatchList id="routines" title="盯盘任务" linkLabel="去例行任务改" to={paths.routines({ tab: "tasks" })} empty={rows.routines.length === 0}>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">{rows.routines.map(routine => <li key={routine.id} data-testid="memory-watch-routine" data-enabled={routine.enabled ? "true" : "false"} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-small text-ink-2">
          <span className="min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{routine.name}</span>
          {!routine.enabled && <StatusBadge kind="neutral" className="h-5">{t("已暂停")}</StatusBadge>}
          <span>{t("范围")}{locale === "en-US" ? ": " : "："}{t(routine.scopeLabel)}{routine.symbols.length > 0 && <span className="font-mono"> {routine.symbols.join(locale === "en-US" ? ", " : "、")}</span>}</span>
          {routine.contents.length > 0 && <span className="min-w-0 [overflow-wrap:anywhere]">{routine.contents.map(item => <span key={item.key} className="mr-2">{t(item.label)}{item.detail && <span className="font-mono"> {item.detail}</span>}</span>)}</span>}
          {routine.next && <span>{t("下次运行")} <span className="font-mono text-ink">{routine.next}</span></span>}
        </li>)}</ul>
      </WatchList>
      <WatchList id="queue" title="研究队列" linkLabel="去研究页看" to={paths.research()} empty={!rows.queue || rows.queue.length === 0}>
        <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0">{(rows.queue ?? []).map(symbol => <li key={symbol} data-testid="memory-watch-queue-symbol" className="font-mono text-small text-ink">{symbol}</li>)}</ul>
      </WatchList>
    </>}
    <WatchRulesSection onChanged={onReload} />
    {rows?.note && <p data-testid="memory-watch-note" className="m-0 text-small text-muted-foreground">{t(rows.note)}</p>}
  </section>;
}
