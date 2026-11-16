import { useState } from "react";
import { Link } from "react-router";
import { StatusBadge } from "@/components/StatusBadge";
import { Timeline, type TimelineItem } from "@/components/Timeline";
import { cn } from "@/lib/utils";
import { Chevron } from "./icons";
import type { V2TimelineEntry } from "../../../types";
import { sourceDiff, versionMethod } from "../../../forecast-detail.mjs";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { day } from "./format";
import type { VersionDetails } from "./useVersionDetails";

const MODEL_CHANGED = "决策模型与上一版不同：概率变化可能来自模型，不一定来自新材料。";

/**
 * 版本侧栏 (design 4.6): the chain as a vertical timeline, newest on top, one item per version (number, date, how it was made).  A press picks the
 * version; the address follows (the page does that).  A version decided by another model than its parent is marked, and the old sentence about it is
 * here, under the version it is about.  The foot: the evidence of this version and what its sources changed against the previous one.  On a desktop it
 * is a sticky column; on a phone it folds into a bar at the top that opens the same list.
 */
export function VersionRail({ versions, selectedId, onSelect, details, changedIds }: { versions: V2TimelineEntry[]; selectedId: string; onSelect: (id: string) => void; details: VersionDetails; changedIds: Set<string> }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const selected = versions.find(version => version.id === selectedId) ?? versions.at(-1);
  const detail = selected ? details.get(selected.id) : undefined;
  const parent = selected?.parent_version_id ? details.get(selected.parent_version_id) : undefined;
  const diff = detail ? sourceDiff(detail, parent ?? null) : null;
  const items: TimelineItem[] = [...versions].reverse().map(version => ({
    id: version.id,
    title: <><span className="font-mono">v{version.version_no}</span> · {t(versionMethod(version).phrase)}</>,
    meta: day(version.decision_at),
    marks: changedIds.has(version.id) ? <StatusBadge kind="neutral" className="h-5" data-testid="model-changed">{t("模型已换")}</StatusBadge> : undefined,
    note: version.id === selectedId && changedIds.has(version.id) ? <p data-testid="model-change-note" className="text-caption text-muted-foreground">{t(MODEL_CHANGED)}</p> : undefined,
  }));
  if (!selected) return null;
  return <aside data-testid="version-rail" aria-label={t("版本")} className="order-first flex min-w-0 flex-col gap-3 lg:sticky lg:top-4 lg:order-none lg:self-start">
    <button type="button" aria-expanded={open} aria-controls="version-rail-list" data-testid="version-rail-toggle" onClick={() => setOpen(value => !value)}
      className="flex min-h-11 items-center gap-2 rounded-md border border-line bg-surface px-3 text-left text-small outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden">
      <span className="min-w-0 flex-1 truncate text-ink"><span className="font-mono">v{selected.version_no}</span> · {day(selected.decision_at)} · {t(versionMethod(selected).phrase)}</span>
      <span className="text-caption text-muted-foreground">{t("切换版本")}</span>
      <Chevron className={cn("text-muted-foreground", open && "rotate-180")} />
    </button>
    <div id="version-rail-list" className={cn("flex-col gap-4 rounded-md border border-line bg-surface p-3", open ? "flex" : "hidden", "lg:flex")}>
      <h2 className="hidden text-small font-medium text-ink lg:block">{t("版本")}</h2>
      <Timeline items={items} selectedId={selected.id} onSelect={id => { onSelect(id); setOpen(false); }} label={t("预测版本")} />
      <div className="flex flex-col gap-1.5 border-t border-line pt-3 text-small">
        <Link to={paths.evidence(selected.id)} data-testid="rail-evidence" className="inline-flex min-h-8 items-center text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
          {detail ? `${t("本版证据")} ${detail.evidence_version_manifest.length} ${t("份")}` : t("本版证据")} →
        </Link>
        <p data-testid="rail-diff" className="text-caption text-muted-foreground">
          {!selected.parent_version_id ? t("第一版，没有上一版可比较。") : diff?.hasParent ? <>{t("与上一版相比：")}<span className="font-mono tabular-nums text-ink">+{diff.added} −{diff.removed}</span></> : t("与上一版相比：…")}
        </p>
      </div>
    </div>
  </aside>;
}
