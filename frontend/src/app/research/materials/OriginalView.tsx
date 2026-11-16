import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SourceQuote } from "@/components/SourceCard";
import type { MaterialItem } from "../../../types";
import { useLocale } from "../../../i18n";
import { httpsUrl } from "../evidence/evidence-model.mjs";

export type CitationSelection = { quote: string; analysisVersion: number } | null;

/**
 * 原始材料 (the fact material): where the original is and, when a quote of an analysis was pressed, that quote in the source's own face.  The original itself
 * is read on the source's site (a new tab); the page does not repeat or re-typeset it.  An uploaded file can be downloaded.
 */
export function OriginalView({ material, citation }: { material: MaterialItem; citation: CitationSelection }) {
  const { t } = useLocale();
  const link = httpsUrl(material.source_url);
  return <article data-testid="original-view" className="material-fact flex min-w-0 flex-col gap-3 px-3 py-3 text-small">
    <p className="text-caption text-muted-foreground">{t(material.source_type === "official_filing" ? "SEC 官方原文" : "原始来源")}</p>
    <h3 className="text-body font-medium text-ink">{t("在来源网站阅读材料")}</h3>
    {citation && <div data-testid="original-quote" className="flex min-w-0 flex-col gap-1">
      <p className="text-caption text-muted-foreground">{t("分析")} v{citation.analysisVersion} {t("引用")}</p>
      <SourceQuote className="border-l-2 border-line-strong pl-3">“{citation.quote}”</SourceQuote>
      <p className="text-caption text-muted-foreground">{t("请打开来源核对这段原文。")}</p>
    </div>}
    {link
      ? <a href={link} target="_blank" rel="noopener noreferrer" data-testid="original-link" className="flex min-w-0 items-center gap-2 rounded-sm border border-line-strong bg-background px-3 py-2 font-mono text-caption text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11"><span className="min-w-0 flex-1 break-all">{material.source_url}</span><ExternalLink aria-hidden="true" className="size-4 shrink-0" /></a>
      : material.source_url ? <p className="break-all font-mono text-caption text-muted-foreground">{material.source_url}</p> : <p className="text-muted-foreground">{t("原始来源链接未记录")}</p>}
    <p className="text-caption text-muted-foreground">{t("原文在新标签页打开，应用内不再重复展示或重新排版整篇正文。")}</p>
    {material.can_download_original && <div><Button asChild variant="outline" size="sm"><a href={`/api/v3/materials/${material.source_type}/${encodeURIComponent(material.source_id)}/download`}>{t("下载上传的原始文件")}</a></Button></div>}
  </article>;
}
