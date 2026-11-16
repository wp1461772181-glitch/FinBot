import { ArrowUpRight } from "lucide-react";
import { OpinionCard, OpinionFacts } from "@/components/OpinionCard";
import { SourceQuote } from "@/components/SourceCard";
import type { MaterialAnalysisVersion, MaterialCitation } from "../../../types";
import { formatDate as formatLocalizedDate, useLocale } from "../../../i18n";
import { citationNote, verificationOf } from "./materials-model.mjs";

type Row = { id: string; statement: string; rationale?: string; reason?: string; citations: MaterialCitation[] };

export function formatDate(value: string | null | undefined, locale: "zh-CN" | "en-US") {
  if (!value) return locale === "en-US" ? "Time not recorded" : "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value.slice(0, 16) : formatLocalizedDate(date, locale, "UTC");
}

/** What the check of a quote says, in the quiet face of a note: it states how the quote was found in the source, it does not judge the conclusion. */
function CheckNote({ citation }: { citation: MaterialCitation }) {
  const { t } = useLocale();
  const note = citationNote(citation);
  if (!note) return null;
  return <p className="flex flex-wrap gap-x-2 text-caption text-muted-foreground">
    <span data-slot="citation-status" data-kind={note.kind}>{t(note.phrase)}{note.percent === null ? "" : ` ${note.percent}%`}</span>
    {note.kind === "unverified" && citation.original_quote && citation.original_quote !== citation.quote && <span>{t("模型原文：")}{citation.original_quote}</span>}
  </p>;
}

/** The quotes under a statement: each is the source's own words in a nested fact block (serif), pressing it goes to the original with the quote shown. */
function Citations({ citations, onLocate }: { citations: MaterialCitation[]; onLocate: (citation: MaterialCitation) => void }) {
  const { t } = useLocale();
  if (!citations?.length) return null;
  return <div data-testid="citations" className="flex min-w-0 flex-col gap-1.5">
    {citations.map((citation, index) => <div key={`${citation.quote}:${index}`} data-slot="citation"><OpinionFacts>
      <SourceQuote><button type="button" aria-label={t("查看这条引文的原始来源")} onClick={() => onLocate(citation)} className="rounded-sm text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">“{citation.quote}”<ArrowUpRight aria-hidden="true" className="ml-1 inline size-3.5 align-text-bottom text-muted-foreground" /></button></SourceQuote>
      <CheckNote citation={citation} />
    </OpinionFacts></div>)}
  </div>;
}

function Section({ title, rows, empty, onLocate }: { title: string; rows: Row[]; empty: string; onLocate: (citation: MaterialCitation) => void }) {
  return <section data-testid="analysis-section" className="flex min-w-0 flex-col gap-2">
    <h3 className="flex items-center gap-2 text-small font-medium text-ink">{title}<span className="font-mono text-caption font-normal text-muted-foreground">{rows.length}</span></h3>
    {rows.length
      ? rows.map(row => <article key={row.id} className="flex min-w-0 flex-col gap-1.5">
          <p className="text-small text-ink [overflow-wrap:anywhere]">{row.statement}</p>
          {(row.rationale || row.reason) && <p className="text-caption text-muted-foreground [overflow-wrap:anywhere]">{row.rationale || row.reason}</p>}
          <Citations citations={row.citations} onLocate={onLocate} />
        </article>)
      : <p className="text-small text-muted-foreground">{empty}</p>}
  </section>;
}

/**
 * One saved analysis of a material, in the opinion material (design 2.2): the model's words under 「模型意见 · 模型 · 版本 · 时间」.  The source's own quotes
 * are the nested fact blocks, in the quote face; the check of each quote is a quiet note beside it.  Nothing here is coloured as a warning: a quote that
 * could not be found word for word is marked 「引用待核对」 and the conclusion stays as it was.
 */
export function AnalysisView({ analysis, onLocateCitation }: { analysis: MaterialAnalysisVersion; onLocateCitation: (citation: MaterialCitation) => void }) {
  const { locale, t } = useLocale();
  const payload = analysis.payload;
  const truncated = Boolean(analysis.source_manifest.truncated || analysis.source_manifest.coverage_incomplete);
  const verification = verificationOf(analysis);
  return <OpinionCard data-testid="analysis-card" data-analysis-id={analysis.analysis_id} model={analysis.actual_model} version={`v${analysis.version_no}`} time={formatDate(analysis.created_at, locale)}>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-muted-foreground">
      <span>{t("分析")} v{analysis.version_no}</span>
      {truncated && <span>{t("仅分析可用摘录")}</span>}
      {verification.total > 0 && <span data-slot="citation-status" data-kind="summary">{t("引用已核对")} {verification.verified}/{verification.total}</span>}
    </div>
    <p data-testid="analysis-summary" className="text-body text-ink [overflow-wrap:anywhere]">{payload.summary}</p>
    {verification.unverified > 0 && <p role="status" data-slot="citation-status" data-kind="note" className="text-caption text-muted-foreground">{t("有")} {verification.unverified} {t("条引文未能在原文中逐字定位，已保留结论并标记为“引用待核对”。")}</p>}
    <Section title={t("原文事实")} rows={payload.facts} empty={t("未提取到有引用支持的事实。")} onLocate={onLocateCitation} />
    <Section title={t("潜在利好")} rows={payload.supporting} empty={t("当前材料没有足够依据支持利好判断。")} onLocate={onLocateCitation} />
    <Section title={t("潜在利空 / 反证")} rows={payload.counter} empty={t("当前材料没有足够依据支持利空判断。")} onLocate={onLocateCitation} />
    <Section title={t("未知与不确定")} rows={payload.uncertainties} empty={t("没有记录额外的不确定项。")} onLocate={onLocateCitation} />
    {payload.key_numbers.length > 0 && <section data-testid="analysis-numbers" className="flex min-w-0 flex-col gap-2">
      <h3 className="text-small font-medium text-ink">{t("关键数字")}</h3>
      {payload.key_numbers.map((item, index) => <div key={`${item.name}:${index}`} className="flex min-w-0 flex-col gap-1.5">
        <p className="flex flex-wrap items-baseline gap-x-3 text-small"><strong className="font-medium text-ink">{item.name}</strong><span className="font-mono tabular-nums text-ink">{item.value_text}{item.period ? ` · ${item.period}` : ""}</span></p>
        <Citations citations={item.citations} onLocate={onLocateCitation} />
      </div>)}
    </section>}
  </OpinionCard>;
}
