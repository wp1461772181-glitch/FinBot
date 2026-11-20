import { FileText, Newspaper } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { SourceCard } from "@/components/SourceCard";
import { cn } from "@/lib/utils";
import type { ResearchBrief, ResearchMaterialReference } from "../../../types";
import { useLocale, colon } from "../../../i18n";
import { day } from "../forecasts/format";
import { eventCount, eventGroups, sourceTypeLabel } from "./evidence-model.mjs";
import { StarsReadout } from "./Stars";

/**
 * One material a version's brief rests on, in the fact material (SourceCard: sunken, colourless, its number at the top right is the number the brief gives it).
 * It shows what the material is (type, title, publication time), the reader's own credibility stars when it is theirs, whether they picked it, and how many of
 * the brief's judgments cite it.  The whole card opens the detail: a button laid over it keeps the keyboard and the screen reader on one control.
 */
export function MaterialCard({ ordinal, source, brief, active, onOpen }: { ordinal: number; source: ResearchMaterialReference; brief: ResearchBrief; active: boolean; onOpen: () => void }) {
  const { locale, t } = useLocale();
  const groups = eventGroups(brief, source.analysis_id, t, locale);
  const count = eventCount(groups);
  const typeLabel = sourceTypeLabel(source.source_type, locale);
  const Icon = source.source_type === "official_filing" ? FileText : Newspaper;
  const title = source.title || typeLabel;
  return <li data-testid="evidence-card" data-source-type={source.source_type} data-source-id={source.source_id} data-active={active ? "" : undefined} className="relative min-w-0 list-none">
    <SourceCard ordinal={ordinal} title={title} meta={[`${t("发布")} ${day(source.published_at)}`]} className={cn("h-full", active && "ring-2 ring-brand")} openLabel="">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-caption text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><Icon aria-hidden="true" className="size-3.5" />{typeLabel}</span>
        <StatusBadge kind="neutral" className="h-5">{source.explicitly_selected ? t("人工选入") : t("简报引用")}</StatusBadge>
        {source.source_type === "uploaded_media" && typeof source.user_rating_stars === "number" && <StarsReadout value={source.user_rating_stars} />}
      </div>
      <p data-testid="card-events" className="text-caption text-ink-2">{count} {t("条关联判断")}{groups.length > 0 && <span className="text-muted-foreground"> · {groups.map(group => group.label).join(" · ")}</span>}</p>
    </SourceCard>
    <button type="button" data-testid="card-open" aria-label={`${t("查看事件详情")}${colon()}${title}`} aria-haspopup="dialog" onClick={onOpen}
      className="absolute inset-0 z-10 m-0 cursor-pointer rounded-[inherit] border-0 bg-transparent p-0 outline-none hover:bg-foreground/[0.03] focus-visible:ring-2 focus-visible:ring-ring appearance-auto" />
  </li>;
}
