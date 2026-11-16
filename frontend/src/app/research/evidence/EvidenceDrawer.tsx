import { ExternalLink } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonCard } from "@/components/state/Skeleton";
import { OpinionCard } from "@/components/OpinionCard";
import type { ResearchBrief, ResearchMaterialReference, V2VersionDetail } from "../../../types";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { day } from "../forecasts/format";
import { briefModel, eventCount, eventGroups, httpsUrl, sectionPhrase, sourceTypeLabel } from "./evidence-model.mjs";
import { StarsReadout } from "./Stars";

type Body = { kind: "loading" } | { kind: "error"; message: string } | { kind: "missing" } | { kind: "ready"; version: V2VersionDetail; brief: ResearchBrief | null; source: ResearchMaterialReference };

/**
 * The detail of one material in one version (design 4.7), a drawer from the right (the whole screen on a phone).  Its address names the version and the
 * material, so it can be opened directly and closed with Back.  The top is the material itself (fact: what it is, when, where from, the reader's own stars);
 * under it the version's brief's events that rest on this material, in six groups, each with the part of the material's analysis it rests on (opinion: the
 * model's words, with the model and version).  A material the version does not cite is said so, not left blank.
 */
export function EvidenceDrawer({ open, body, versionHref, onClose, returnFocus }: { open: boolean; body: Body; versionHref: string; onClose: () => void; returnFocus: () => void }) {
  const { locale, t } = useLocale();
  const ready = body.kind === "ready" ? body : null;
  const groups = ready?.brief ? eventGroups(ready.brief, ready.source.analysis_id, t, locale) : [];
  const count = eventCount(groups);
  const source = ready?.source ?? null;
  const officialUrl = httpsUrl(source?.source_url);
  const typeLabel = source ? sourceTypeLabel(source.source_type, locale) : "";
  const title = source ? source.title || typeLabel : t("材料详情");
  return <Drawer open={open} onOpenChange={next => { if (!next) onClose(); }} direction="right">
    <DrawerContent data-testid="evidence-drawer" aria-describedby="evidence-drawer-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus(); }}
      className="outline-none data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-xl">
      <DrawerHeader className="gap-1.5 border-b border-line">
        <p className="text-caption text-muted-foreground">{source ? `${typeLabel} · ${t("第")} ${ready!.version.version_no} ${t("版")}` : t("证据")}</p>
        <DrawerTitle className="text-title-s [overflow-wrap:anywhere]">{title}</DrawerTitle>
        <DrawerDescription id="evidence-drawer-description" className="text-small">
          {source ? `${t("发布")} ${day(source.published_at)} · ${t("观察")} ${day(source.observed_at)} · ${count} ${t("条关联判断")}` : t("这份材料在这个预测版本里的事件与依据。")}
        </DrawerDescription>
      </DrawerHeader>
      <div data-testid="evidence-drawer-body" className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        {body.kind === "loading" && <DelayedSkeleton><SkeletonCard /></DelayedSkeleton>}
        {body.kind === "error" && <ErrorBar message={body.message} />}
        {body.kind === "missing" && <EmptyState title={t("该版本没有引用这份材料")} description={t("证据页只展示研究简报实际引用的材料。可以返回列表选择其他材料。")} action={{ label: t("返回列表"), to: versionHref }} className="rounded-md border border-dashed border-line" />}
        {ready && source && <>
          <section data-testid="drawer-material" className="material-fact flex min-w-0 flex-col gap-2 px-3 py-3 text-small">
            <div className="flex flex-wrap items-center gap-2">
              {officialUrl
                ? <Button asChild variant="outline" size="sm"><a href={officialUrl} target="_blank" rel="noopener noreferrer" data-testid="open-source">{t("打开原始来源")}<ExternalLink aria-hidden="true" /></a></Button>
                : <span className="text-muted-foreground">{t("原始来源链接未记录")}</span>}
              <Button asChild variant="outline" size="sm"><Link data-testid="open-analysis" to={paths.materials({ symbol: source.symbol, focus: source.source_id, type: source.source_type, analysis: source.analysis_id })}>{t("查看完整材料分析")}</Link></Button>
            </div>
            {source.source_type === "uploaded_media" && typeof source.user_rating_stars === "number" && <p data-testid="drawer-rating" className="flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-2">
              <span>{t("你给的可信度")}</span><StarsReadout value={source.user_rating_stars} /><span className="text-muted-foreground">· {source.user_rating_label ? t(source.user_rating_label) : t("上传时的用户判断")}</span>
            </p>}
            {(source.coverage_incomplete || source.truncated) && <p className="text-caption text-muted-foreground">{t("该材料只覆盖了部分原文，事件判断受可用内容范围限制。")}</p>}
          </section>
          {groups.length > 0
            ? <OpinionCard data-testid="drawer-events" model={briefModel(ready.version)} version={`v${ready.version.version_no}`} time={day(ready.version.decision_at)}
                footnote={<p>{t("标签表示该事件在第")} {ready.version.version_no} {t("版研究简报中的作用；“潜在利好 / 利空”对应这版研究判断，不是脱离预测方向的通用情绪分类。")}</p>}>
                {groups.map(group => <section key={group.key} data-testid="event-group" data-group={group.key} className="flex min-w-0 flex-col gap-2">
                  <h3 className="flex items-center gap-2 text-small font-medium text-ink">{group.label}<span className="font-mono text-caption font-normal text-muted-foreground">{group.rows.length}</span></h3>
                  <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {group.rows.map((row, index) => <li key={`${group.key}:${index}`} data-testid="event" className="flex min-w-0 flex-col gap-1.5">
                      <p className="text-small text-ink [overflow-wrap:anywhere]">{row.text}</p>
                      <p data-testid="event-basis" className="text-caption text-muted-foreground">{t("依据该材料分析中的")} {row.citations.map(citation => `${t(sectionPhrase(citation.section))} #${citation.item_id}`).join(" · ")}</p>
                    </li>)}
                  </ul>
                </section>)}
              </OpinionCard>
            : <EmptyState title={t("简报没有从这份材料中提取事件判断")} description={t("该材料被简报引用，但没有关联到新增事实、利好、利空或不确定项。可在材料库查看完整分析。")}
                action={{ label: t("打开材料分析"), to: paths.materials({ symbol: source.symbol, focus: source.source_id, type: source.source_type, analysis: source.analysis_id }) }} className="rounded-md border border-dashed border-line" />}
        </>}
      </div>
    </DrawerContent>
  </Drawer>;
}
