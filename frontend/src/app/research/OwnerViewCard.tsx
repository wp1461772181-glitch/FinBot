import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorBar } from "@/components/state/ErrorBar";
import { SkeletonCard } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { deleteOwnerView, getOwnerViewHistory, type OwnerViewVersion } from "../../api/owner-views";
import { useLocale } from "../../i18n";
import { dayLabel, hasAnyView, splitVersions, statusPhrase, versionSpan } from "../../owner-views.mjs";
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

  return <section data-testid="owner-view" aria-label={t("你的看法")} className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-4">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 className="text-title-s text-ink">{t("你的看法")}</h2>
      {active && <p data-testid="owner-view-date" className="m-0 font-mono text-caption text-muted-foreground">{saidOn(active.created_at, locale, t)}</p>}
    </div>
    {active
      ? <>
        <p data-testid="owner-view-text" className="m-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{active.text}</p>
        <Quote text={active.quote} />
      </>
      : <p data-testid="owner-view-none" className="m-0 text-small text-muted-foreground">{t("目前没有看法")}</p>}
    {failure != null && <ErrorBar message={actionMessage(failure, "删除失败，请重试。")} />}
    {earlier.length > 0 && <Collapsible open={open} onOpenChange={setOpen} data-testid="owner-view-history" className="border-t border-line pt-2">
      <CollapsibleTrigger data-testid="owner-view-history-toggle" className="group/fold flex min-h-11 items-center gap-1.5 rounded-sm text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />{t("历史")}<span className="font-mono text-caption text-muted-foreground">· {earlier.length}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="m-0 flex list-none flex-col gap-3 p-0 pt-2">{earlier.map(version => <li key={version.id} data-testid="owner-view-version" data-status={version.status} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-sunken p-3">
          <div className="flex flex-wrap items-center gap-2">
            {statusPhrase(version.status) && <StatusBadge kind="neutral" className="h-5">{t(statusPhrase(version.status))}</StatusBadge>}
            <span className="font-mono text-caption text-muted-foreground">{versionSpan(version, locale)}</span>
            <Button type="button" size="sm" variant="ghost" data-testid="owner-view-delete" disabled={busy === version.id} aria-label={`${t("删除")} · ${version.text}`} className="ml-auto text-danger max-md:h-11" onClick={event => void remove(version, event.currentTarget)}>{t("删除")}</Button>
          </div>
          <p className="m-0 text-small text-ink [overflow-wrap:anywhere]">{version.text}</p>
          <Quote text={version.quote} />
        </li>)}</ul>
      </CollapsibleContent>
    </Collapsible>}
  </section>;
}
