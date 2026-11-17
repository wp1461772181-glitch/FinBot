import { StatTile } from "@/components/StatTile";
import { StatusBadge } from "@/components/StatusBadge";
import type { V2VersionDetail } from "../../../types";
import { useLocale } from "../../../i18n";
import { evidenceTitle, processingStatus, sourceKey } from "../forecasts/processing";

/**
 * 本次预测的材料范围: the frozen candidate sources of the replayed forecast and what became of each in the research brief.  The frozen list is the sources that were
 * available at the decision time; the model reads the validated brief and its citations, not every candidate.  (The old page's 「冻结候选与简报材料范围」 block.)
 */
export function ReplayMaterials({ version }: { version: V2VersionDetail }) {
  const { t } = useLocale();
  const brief = version.research_brief ?? null;
  const sources = version.evidence_version_manifest;
  const included = new Set((brief?.material_refs ?? []).map(sourceKey));
  const includedCount = sources.filter(item => included.has(sourceKey(item))).length;
  return <section data-testid="replay-materials" aria-labelledby="replay-materials-title" className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-col gap-0.5"><p className="m-0 text-caption text-muted-foreground">{t("本次预测的材料范围")}</p><h3 id="replay-materials-title" className="text-title-s text-ink">{t("冻结候选不等于模型实际输入")}</h3></div>
    <div className="grid grid-cols-3 gap-3">
      <StatTile label={t("冻结候选")} value={sources.length} />
      <StatTile label={t("分析成功并进入简报")} value={includedCount} />
      <StatTile label={t("未进入简报")} value={sources.length - includedCount} />
    </div>
    <p className="m-0 text-caption text-muted-foreground">{t("冻结清单保存预测当时可用的来源快照。模型读取的是通过校验的研究简报及其引用，不会直接读取所有候选。")}</p>
    {sources.length === 0
      ? <p className="m-0 text-small text-muted-foreground">{t("该版本没有冻结材料候选。")}</p>
      : <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {sources.map((item, index) => {
          const ref = brief?.material_refs.find(candidate => sourceKey(candidate) === sourceKey(item));
          const status = processingStatus(item, brief, t);
          const url = typeof item.source_url === "string" && item.source_url ? item.source_url : ref?.source_url ?? null;
          return <li key={`${sourceKey(item)}:${index}`} className="material-fact flex min-w-0 flex-col gap-1 px-3 py-2">
            <strong className="text-small font-medium text-ink [overflow-wrap:anywhere]">{evidenceTitle(item, ref)}</strong>
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1"><StatusBadge kind={status.tone === "included" ? "success" : "neutral"} className="h-5">{status.label}</StatusBadge></span>
            <span className="text-caption text-muted-foreground">{status.detail}</span>
            {url && <a href={url} target="_blank" rel="noopener noreferrer" className="w-fit text-small font-medium text-brand underline-offset-2 hover:underline">{t("打开原始来源")}</a>}
          </li>;
        })}
      </ul>}
  </section>;
}
