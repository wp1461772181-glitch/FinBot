import { useState } from "react";
import { Link } from "react-router";
import { ArrowRight, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { dropOwnerView, writeOwnerView, type OverviewCompany } from "../../../api/memory-overview";
import { deleteOwnerView, restoreOwnerView, type OwnerViewVersion } from "../../../api/owner-views";
import { useLocale } from "../../../i18n";
import { typedOnPage, viewGroups, type ViewGroup } from "../../../memory-overview.mjs";
import { statusPhrase, versionSpan } from "../../../owner-views.mjs";
import { paths } from "../../../routes.mjs";
import { LookBack, Quote, saidOn } from "../../research/OwnerViewCard";
import { MAX_TEXT } from "./memory-view.mjs";

/** The line that stands where a quote would be for a view he typed on this page: there is no conversation behind it. */
function PageTyped() {
  const { t } = useLocale();
  return <p data-testid="owner-view-page-typed" className="m-0 text-caption text-muted-foreground">{t("在记忆页写的")}</p>;
}

/**
 * One company on the memory page: its current view (his words, the date, the latest 回头看), 改 and 撤回, and every earlier version in a fold (each can be deleted; an archived one can be
 * brought back).  A company with no current view has the fold and 重新写一条.  A change here is made the way saying it in conversation makes it: a new version, the old one kept.
 */
function CompanyCard({ company, former, onChanged }: { company: ViewGroup; former: boolean; onChanged: () => Promise<void> }) {
  const { t, locale } = useLocale();
  const [editing, setEditing] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const { current, history, symbol } = company;

  async function run(key: string, work: () => Promise<unknown>): Promise<boolean> {
    setBusy(key); setFailure(null);
    try { await work(); await onChanged(); return true; }
    catch (error) { setFailure(error); return false; }
    finally { setBusy(null); }
  }
  async function save() {
    if (editing === null || !editing.trim()) return;
    const text = editing.trim();
    if (await run("write", () => writeOwnerView(symbol, text))) setEditing(null);
  }
  async function drop(from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: t("撤回这条看法？"), description: t("撤回后它不再按这条看法回答，历史里还留着。"), confirmLabel: t("撤回"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (yes) await run("drop", () => dropOwnerView(symbol));
  }
  async function remove(version: OwnerViewVersion, from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: t("删除这条历史？"), description: t("删除后无法恢复"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (yes) await run(version.id, () => deleteOwnerView(version.id));
  }

  const editor = <div className="flex min-w-0 flex-wrap items-center gap-2">
    <Input value={editing ?? ""} maxLength={MAX_TEXT} autoFocus aria-label={`${t("你的看法")} · ${symbol}`} data-testid="owner-view-input" className="min-w-0 flex-1 basis-60 max-md:h-11"
      onChange={event => setEditing(event.target.value)}
      onKeyDown={event => { if (event.nativeEvent.isComposing) return; if (event.key === "Enter") { event.preventDefault(); void save(); } if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setEditing(null); } }} />
    <Button type="button" size="sm" data-testid="owner-view-save" disabled={busy === "write" || !editing?.trim()} className="max-md:h-11" onClick={() => void save()}>{t("保存")}</Button>
    <Button type="button" size="sm" variant="ghost" data-testid="owner-view-cancel" className="max-md:h-11" onClick={() => setEditing(null)}>{t("取消")}</Button>
  </div>;

  return <li data-testid="owner-view-item" data-symbol={symbol} data-former={former ? "true" : undefined} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
      <span data-testid="owner-view-symbol" className="font-mono text-body font-medium text-ink">{symbol}</span>
      {company.name && company.name !== symbol && <span className="text-small text-muted-foreground [overflow-wrap:anywhere]">{company.name}</span>}
      {current && <span className="font-mono text-caption text-muted-foreground">{saidOn(current.created_at, locale, t)}</span>}
      <Link to={paths.company(symbol)} data-testid="owner-view-link" aria-label={`${t("打开公司页")} · ${symbol}`} className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-sm text-small text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring md:min-h-0">{t("打开公司页")}<ArrowRight aria-hidden="true" className="size-3.5" /></Link>
    </div>
    {current && editing === null && <>
      <p data-testid="owner-view-text" className="m-0 text-body text-ink [overflow-wrap:anywhere]">{current.text}</p>
      {typedOnPage(current) ? <PageTyped /> : <Quote text={current.quote} />}
      <LookBack version={current} />
    </>}
    {editing !== null && editor}
    {failure != null && <ErrorBar error={failure} />}
    {editing === null && <div className="flex flex-wrap items-center gap-2">
      <span className="ml-auto" />
      {current
        ? <>
          <Button type="button" size="sm" variant="ghost" data-testid="owner-view-edit" disabled={busy !== null} aria-label={`${t("改")} · ${current.text}`} className="max-md:h-11" onClick={() => setEditing(current.text)}>{t("改")}</Button>
          <Button type="button" size="sm" variant="ghost" data-testid="owner-view-drop" disabled={busy !== null} aria-label={`${t("撤回")} · ${current.text}`} className="text-danger max-md:h-11" onClick={event => void drop(event.currentTarget)}>{t("撤回")}</Button>
        </>
        : <Button type="button" size="sm" variant="outline" data-testid="owner-view-rewrite" disabled={busy !== null} aria-label={`${t("重新写一条")} · ${symbol}`} className="max-md:h-11" onClick={() => setEditing("")}>{t("重新写一条")}</Button>}
    </div>}
    {history.length > 0 && <Collapsible open={open} onOpenChange={setOpen} data-testid="owner-view-history" className="border-t border-line pt-2">
      <CollapsibleTrigger data-testid="owner-view-history-toggle" className="group/fold flex min-h-11 items-center gap-1.5 rounded-sm text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />{t("历史")}<span className="font-mono text-caption text-muted-foreground">· {history.length}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="m-0 flex list-none flex-col gap-3 p-0 pt-2">{history.map(version => <li key={version.id} data-testid="owner-view-version" data-status={version.status} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-sunken p-3">
          <div className="flex flex-wrap items-center gap-2">
            {statusPhrase(version.status) && <StatusBadge kind="neutral" className="h-5">{t(statusPhrase(version.status))}</StatusBadge>}
            <span className="font-mono text-caption text-muted-foreground">{versionSpan(version, locale)}</span>
            {version.status === "archived" && version.archived_reason && <span data-testid="owner-view-archived-note" className="min-w-0 text-caption text-muted-foreground">{t(version.archived_reason)}</span>}
            <span className="ml-auto" />
            {version.status === "archived" && <Button type="button" size="sm" variant="outline" data-testid="owner-view-restore" disabled={busy !== null} aria-label={`${t("恢复")} · ${version.text}`} className="max-md:h-11" onClick={() => void run(version.id, () => restoreOwnerView(version.id))}>{t("恢复")}</Button>}
            <Button type="button" size="sm" variant="ghost" data-testid="owner-view-delete" disabled={busy !== null} aria-label={`${t("删除")} · ${version.text}`} className="text-danger max-md:h-11" onClick={event => void remove(version, event.currentTarget)}>{t("删除")}</Button>
          </div>
          <p className="m-0 text-small text-ink [overflow-wrap:anywhere]">{version.text}</p>
          {typedOnPage(version) ? <PageTyped /> : <Quote text={version.quote} />}
          <LookBack version={version} />
        </li>)}</ul>
      </CollapsibleContent>
    </Collapsible>}
  </li>;
}

/**
 * 你的看法 (the 它眼中的你 tab): every company he has said a view of, with all its versions and the latest 回头看.  The data is the overview's (one request for the page, read by
 * MemoryPage).  He can change a view or withdraw it here, directly: the old one is kept in the history.  A view is not evidence.  `failed`: this part could not be read.
 */
export function OwnerViewsPanel({ views, failed, loading, onReload }: { views: OverviewCompany[] | null; failed: boolean; loading: boolean; onReload: () => Promise<void> }) {
  const { t } = useLocale();
  const groups = viewGroups(views);
  const total = groups.current.length;
  const none = views !== null && groups.current.length === 0 && groups.former.length === 0;
  return <section data-testid="owner-views" aria-labelledby="owner-views-title" className="flex min-w-0 flex-col gap-2">
    <h2 id="owner-views-title" className="text-title-s text-ink">{t("你的看法")}{views && total > 0 && <span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{total}</span>}</h2>
    {failed && <ErrorBar message={t("这一部分暂时读不出来。")} onRetry={() => void onReload()} retrying={loading} />}
    {!views && !failed && loading && <DelayedSkeleton><div role="status" aria-busy="true" className="flex flex-col gap-2"><span className="sr-only">{t("正在读取")}</span>{[0, 1].map(i => <Skeleton key={i} className="h-20 w-full" />)}</div></DelayedSkeleton>}
    {none && <div data-testid="owner-views-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("还没有记下对哪家公司的看法。在对话里说出你的看法，它会记下来。")} /></div>}
    {groups.current.length > 0 && <ul className="m-0 flex list-none flex-col gap-2 p-0">{groups.current.map(company => <CompanyCard key={company.symbol} company={company} former={false} onChanged={onReload} />)}</ul>}
    {groups.former.length > 0 && <div data-testid="owner-views-former" className="mt-2 flex min-w-0 flex-col gap-2">
      <h3 className="text-small font-medium text-ink-2">{t("以前的看法")}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{groups.former.length}</span></h3>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">{groups.former.map(company => <CompanyCard key={company.symbol} company={company} former onChanged={onReload} />)}</ul>
    </div>}
  </section>;
}
