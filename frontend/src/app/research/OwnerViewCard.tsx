import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorBar } from "@/components/state/ErrorBar";
import { SkeletonCard } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { deleteOwnerView, getOwnerViewHistory, restoreOwnerView, type OwnerViewReview, type OwnerViewVersion } from "../../api/owner-views";
import { useLocale } from "../../i18n";
import { archivedCurrent, basisLine, dayLabel, hasAnyView, reviewOf, splitVersions, statusPhrase, strayFigures, verdictBadge, versionSpan } from "../../owner-views.mjs";
import { useWorkspace } from "../workspace";
import { actionMessage } from "./support";
import { useRead } from "./use-read";

/** The date a view was said: 「M月D日 说的」 in Chinese, "said M/D" in English. */
function saidOn(value: string | null, locale: string, t: (text: string) => string): string {
  const day = dayLabel(value, locale);
  if (!day) return "";
  return locale === "en-US" ? `${t("说的")} ${day}` : `${day} ${t("说的")}`;
}

function Quote({ text, className = "" }: { text: string; className?: string }) {
  const { t } = useLocale();
  if (!text.trim()) return null;
  return <div className={`flex min-w-0 flex-col gap-0.5 ${className}`}>
    <p className="m-0 text-caption text-muted-foreground">{t("你的原话")}</p>
    <blockquote data-testid="owner-view-quote" className="m-0 border-l-2 border-line pl-3 font-quote text-small text-ink-2 [overflow-wrap:anywhere]">“{text}”</blockquote>
  </div>;
}

/**
 * 回头看: the quarterly look back at one version.  The review text is shown exactly as stored; the basis line is the code's own snapshot (a part with no data is left out);
 * the caution appears only when the system could not find some figure of the review in the data it gave, and names those figures so the owner can check them himself.
 */
function LookBack({ version }: { version: OwnerViewVersion }) {
  const { t, locale } = useLocale();
  const review = reviewOf(version) as OwnerViewReview | null;
  if (!review) return null;
  const badge = verdictBadge(review) as { label: string; kind: string };
  const basis = basisLine(review.basis, { then: t("说的时候"), now: t("现在"), quarter: t("最新一季") }) as string;
  const stray = strayFigures(review) as string[];
  return <div data-testid="owner-view-review" data-verdict={review.verdict} className="flex min-w-0 flex-col gap-1.5 rounded-md border border-line bg-surface p-3">
    <div className="flex flex-wrap items-center gap-2">
      <p className="m-0 text-caption text-muted-foreground">{t("回头看")}</p>
      {badge.label && <StatusBadge kind={badge.kind} className="h-5">{t(badge.label)}</StatusBadge>}
    </div>
    <p data-testid="owner-view-review-text" className="m-0 text-small text-ink [overflow-wrap:anywhere]">{review.text}</p>
    {basis && <p data-testid="owner-view-review-basis" className="m-0 font-mono text-caption text-muted-foreground [overflow-wrap:anywhere]">{basis}</p>}
    {stray.length > 0 && <p data-testid="owner-view-review-stray" className="m-0 text-caption text-muted-foreground [overflow-wrap:anywhere]">{t("这几个数字不在系统给的资料里，请自己核对：")}{stray.join(locale === "en-US" ? ", " : "、")}</p>}
  </div>;
}

/**
 * 你的看法 (the company page): what the owner said he thinks of this company, in his own words, and the versions before it.  Written in conversation, never here: the page shows
 * and deletes.  No view and no history: no card at all.  Owner only (a guest has none; the card is not read for a guest).
 */
export function OwnerViewCard({ symbol }: { symbol: string }) {
  const { t, locale } = useLocale();
  const ws = useWorkspace();
  const [versions, retry] = useRead(`owner-views:${symbol}`, signal => getOwnerViewHistory(symbol, signal), ws.personal);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  if (!ws.personal) return null;
  if (versions.kind === "loading") return <SkeletonCard className="h-24" />;
  if (versions.kind === "error") return <section data-testid="owner-view" aria-label={t("你的看法")} className="flex flex-col gap-2 rounded-md border border-line bg-surface p-4">
    <h2 className="text-title-s text-ink">{t("你的看法")}</h2>
    <ErrorBar message={actionMessage(versions.error, "你的看法暂时无法读取。")} onRetry={retry} />
  </section>;
  if (!hasAnyView(versions.value)) return null;
  const { active, earlier } = splitVersions(versions.value) as { active: OwnerViewVersion | null; earlier: OwnerViewVersion[] };

  async function remove(version: OwnerViewVersion, from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: t("删除这条历史？"), description: t("删除后无法恢复"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (!yes) return;
    setBusy(version.id); setFailure(null);
    try { await deleteOwnerView(version.id); retry(); }
    catch (error) { setFailure(error); }
    finally { setBusy(null); }
  }

  const archivedNow = archivedCurrent(versions.value) as OwnerViewVersion | null;
  const history = archivedNow ? earlier.filter(version => version !== archivedNow) : earlier;
  async function restore(version: OwnerViewVersion) {
    setBusy(version.id); setFailure(null);
    try { await restoreOwnerView(version.id); retry(); }
    catch (error) { setFailure(error); }
    finally { setBusy(null); }
  }
  const archivedLine = (version: OwnerViewVersion) => <p data-testid="owner-view-archived-note" className="m-0 text-caption text-muted-foreground">{version.archived_reason ? `${t(version.archived_reason)} · ` : ""}<span className="font-mono">{dayLabel(version.ended_at, locale) && (locale === "en-US" ? `${t("已归档")} ${dayLabel(version.ended_at, locale)}` : `${dayLabel(version.ended_at, locale)} ${t("已归档")}`)}</span></p>;

  return <section data-testid="owner-view" aria-label={t("你的看法")} className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-4">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 className="text-title-s text-ink">{t("你的看法")}</h2>
      {active && <p data-testid="owner-view-date" className="m-0 font-mono text-caption text-muted-foreground">{saidOn(active.created_at, locale, t)}</p>}
    </div>
    {active
      ? <>
        <p data-testid="owner-view-text" className="m-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{active.text}</p>
        <Quote text={active.quote} />
        <LookBack version={active} />
      </>
      : archivedNow
        ? <div data-testid="owner-view-archived" className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge kind="neutral" className="h-5">{t("已归档")}</StatusBadge>
            <Button type="button" size="sm" variant="outline" data-testid="owner-view-restore" disabled={busy === archivedNow.id} aria-label={`${t("恢复")} · ${archivedNow.text}`} className="ml-auto max-md:h-11" onClick={() => void restore(archivedNow)}>{t("恢复")}</Button>
          </div>
          <p data-testid="owner-view-text" className="m-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{archivedNow.text}</p>
          {archivedLine(archivedNow)}
          <Quote text={archivedNow.quote} />
          <LookBack version={archivedNow} />
        </div>
        : <p data-testid="owner-view-none" className="m-0 text-small text-muted-foreground">{t("目前没有看法")}</p>}
    {failure != null && <ErrorBar message={actionMessage(failure, "操作失败，请重试。")} />}
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
            <Button type="button" size="sm" variant="ghost" data-testid="owner-view-delete" disabled={busy === version.id} aria-label={`${t("删除")} · ${version.text}`} className="ml-auto text-danger max-md:h-11" onClick={event => void remove(version, event.currentTarget)}>{t("删除")}</Button>
          </div>
          <p className="m-0 text-small text-ink [overflow-wrap:anywhere]">{version.text}</p>
          <Quote text={version.quote} />
          <LookBack version={version} />
        </li>)}</ul>
      </CollapsibleContent>
    </Collapsible>}
  </section>;
}
