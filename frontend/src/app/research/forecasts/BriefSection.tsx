import { useState } from "react";
import { Link } from "react-router";
import { OpinionCard, OpinionFacts } from "@/components/OpinionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import { Chevron } from "./icons";
import type { ResearchBrief, ResearchEvidencePointer, ResearchMaterialReference, V2VersionDetail } from "../../../types";
import { forecastCopy, recordedModel } from "../../../forecast-model.mjs";
import { asText } from "../../../ForecastShared";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { useAiContentLocalization, withLocalizedFields } from "../../../useAiContentLocalization";
import { day, money, numberText, percent2 } from "./format";

type Locale = "zh-CN" | "en-US";

const sectionText = (value: ResearchEvidencePointer["section"], locale: Locale) => (locale === "en-US" ? { facts: "facts", supporting: "positives", counter: "negatives", uncertainties: "uncertainties" } : { facts: "事实", supporting: "利好", counter: "利空", uncertainties: "不确定项" })[value];
const sourceTypeLabel = (value: string, locale: Locale) => locale === "en-US" ? (value === "official_filing" ? "SEC filing" : "Uploaded material") : (value === "official_filing" ? "SEC 官方来源" : "用户上传材料");
const changeLabel = (value: string, t: (text: string) => string) => ({ added: t("新增"), withdrawn: t("撤回"), modified: t("修订"), source_status_changed: t("来源状态变化") } as Record<string, string>)[value] ?? value;

/** The source numbers of one statement: every citation is a [n] chip that opens that material on the evidence page (the number is the material's place in 纳入简报的材料). */
type CiteTarget = "evidence" | "materials";
/** Where a citation or a material's link goes: the evidence page (a forecast's brief), or the material library on that material's analysis (a historical replay's brief, which has no evidence page of its own). */
const cite = (target: CiteTarget, versionId: string, material: ResearchMaterialReference) => target === "materials"
  ? paths.materials({ symbol: material.symbol, focus: material.source_id, type: material.source_type, analysis: material.analysis_id })
  : paths.evidence(versionId, material.source_type, material.source_id);

function Cites({ citations, materials, versionId, target }: { citations: ResearchEvidencePointer[]; materials: ResearchMaterialReference[]; versionId: string; target: CiteTarget }) {
  const { t, locale } = useLocale();
  if (!citations.length) return null;
  return <span data-slot="brief-cites" className="flex flex-wrap gap-1.5">
    {citations.map((citation, index) => {
      const at = materials.findIndex(material => material.analysis_id === citation.analysis_id);
      const material = materials[at];
      if (!material) return null;
      const what = `${material.title || sourceTypeLabel(material.source_type, locale)} · ${sectionText(citation.section, locale)} ${citation.item_id}`;
      return <Link key={`${citation.analysis_id}:${citation.section}:${citation.item_id}:${index}`} to={cite(target, versionId, material)} data-slot="brief-cite" title={what} aria-label={`${t("来源")} ${at + 1}：${what}`}
        className="inline-flex h-6 items-center gap-1 rounded-sm border border-line-strong bg-background px-1.5 font-mono text-caption text-ink-2 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">[{at + 1}]<span className="font-sans text-muted-foreground">{sectionText(citation.section, locale)} {citation.item_id}</span></Link>;
    })}
  </span>;
}

function Group<T extends { citations: ResearchEvidencePointer[] }>({ title, rows, text, materials, versionId, target, facts = false }: { title: string; rows: T[]; text: (row: T) => string; materials: ResearchMaterialReference[]; versionId: string; target: CiteTarget; facts?: boolean }) {
  if (rows.length === 0) return null;
  return <section data-slot="brief-group" className="flex min-w-0 flex-col gap-2">
    <h4 className="flex items-baseline gap-2 text-small font-medium text-ink">{title}<span className="font-mono text-caption font-normal text-muted-foreground">{rows.length}</span></h4>
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {rows.map((row, index) => <li key={`${text(row)}:${index}`} className="min-w-0">
        {facts
          ? <OpinionFacts><p className="[overflow-wrap:anywhere]">{text(row)}</p><Cites citations={row.citations} materials={materials} versionId={versionId} target={target} /></OpinionFacts>
          : <div className="flex flex-col gap-1.5"><p className="text-body text-ink [overflow-wrap:anywhere]">{text(row)}</p><Cites citations={row.citations} materials={materials} versionId={versionId} target={target} /></div>}
      </li>)}
    </ul>
  </section>;
}

/**
 * 研究简报 (design 4.6): the model's reading of the version's saved materials, one collapsible section on the opinion material.  What a statement rests on
 * is a nested fact block with its source numbers; the model's own summaries (利好, 利空, 未知问题) are plain opinion text.  Every number opens the material on
 * the evidence page.  The groups and their data are the old brief's.
 */
export function BriefSection({ version, brief: saved, citeTarget = "evidence" }: { version: V2VersionDetail; brief: ResearchBrief; citeTarget?: CiteTarget }) {
  const { t, locale } = useLocale();
  const [open, setOpen] = useState(true);
  const localization = useAiContentLocalization("forecast_brief", version.id);
  const brief = localization.kind === "ready" ? withLocalizedFields(saved, localization.fields) : saved;
  const market = brief.market_summary;
  const target = brief.target_contract;
  const materials = brief.material_refs;
  const provider = (version.model_manifest.decision_provider ?? {}) as Record<string, unknown>;
  const { actual_model } = recordedModel(version);
  const copy = forecastCopy({ model_status: version.model_status, provider: asText(provider.provider), actual_model: asText(provider.actual_model) });
  const quality = ({ ready: t("可用"), limited: t("受限"), insufficient: t("不足") })[brief.input_quality.status];
  const stat = (label: string, value: string) => <div key={label}><dt className="text-caption text-muted-foreground">{label}</dt><dd className="m-0 font-mono text-small tabular-nums text-ink">{value}</dd></div>;
  return <OpinionCard data-testid="forecast-brief" model={actual_model} version={`v${version.version_no}`} time={day(brief.decision_at)}>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h2 id="forecast-brief-title" className="text-title-s text-ink">{t("研究简报")}</h2>
      <StatusBadge kind="neutral" className="h-5">{quality} · {t("输入质量")}</StatusBadge>
      <p className="text-caption text-muted-foreground">{brief.symbol} · {t("截止")} {day(brief.decision_at)}</p>
      <button type="button" aria-expanded={open} aria-controls="forecast-brief-body" data-testid="brief-toggle" onClick={() => setOpen(value => !value)}
        className="ml-auto inline-flex h-8 items-center gap-1 rounded-sm px-2 text-small text-ink-2 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11">
        {open ? t("收起") : t("展开")}<Chevron className={cn("transition-transform", open && "rotate-180")} />
      </button>
    </div>
    <div id="forecast-brief-body" hidden={!open} className="flex min-w-0 flex-col gap-4">
      {locale === "en-US" && localization.kind === "loading" && <p role="status" className="text-caption text-muted-foreground">{t("Translating saved research brief…")}</p>}
      {locale === "en-US" && localization.kind === "error" && <p role="status" className="text-caption text-muted-foreground">{t("English translation is temporarily unavailable; showing the saved original.")}</p>}
      {brief.time_mode === "historical_research" && <p className="text-small text-ink-2">{t("这是使用现行流程对历史时点进行的回放；材料和行情可能在当时之后才被系统获取，结果属于历史研究，不计入真实前向表现。")}</p>}
      <OpinionFacts className="gap-2">
        <p className="text-caption font-medium text-muted-foreground">{t("固定目标与市场快照")}</p>
        <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          {stat(t("固定目标日"), asText(target.target_end_date) ?? t("未记录"))}
          {stat(t("原始锚点收盘"), money(target.anchor_close))}
          {stat(t("最近收盘"), money(market.latest_close))}
          {stat(t("行情截止"), day(asText(market.as_of)))}
          {stat(t("近 5 个交易日"), percent2(market.return_5_sessions))}
          {stat(t("近 20 个交易日"), percent2(market.return_20_sessions))}
          {stat(t("20 日波动"), percent2(market.volatility_20_sessions))}
          {stat(t("距目标剩余交易日"), numberText(market.remaining_sessions))}
        </dl>
      </OpinionFacts>
      {brief.input_quality.reasons.length > 0 && <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-small text-ink-2">{brief.input_quality.reasons.map((reason, index) => <li key={`${reason}:${index}`}>{reason}</li>)}</ul>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Group title={t("新增事实")} rows={brief.new_facts} text={row => row.statement} materials={materials} versionId={version.id} target={citeTarget} facts />
        <Group title={t("持续背景")} rows={brief.background} text={row => locale === "en-US" ? `${row.statement} (Continuing reason: ${row.continuing_reason})` : `${row.statement}（持续原因：${row.continuing_reason}）`} materials={materials} versionId={version.id} target={citeTarget} facts />
        <Group title={t("潜在利好")} rows={brief.supporting} text={row => row.statement} materials={materials} versionId={version.id} target={citeTarget} />
        <Group title={t("潜在利空 / 反证")} rows={brief.counter} text={row => row.statement} materials={materials} versionId={version.id} target={citeTarget} />
        <Group title={t("来源冲突")} rows={brief.conflicts} text={row => row.description} materials={materials} versionId={version.id} target={citeTarget} />
        <Group title={t("未知问题")} rows={brief.unknowns} text={row => locale === "en-US" ? `${row.question}: ${row.reason}` : `${row.question}：${row.reason}`} materials={materials} versionId={version.id} target={citeTarget} />
        <Group title={t("版本变化")} rows={brief.changes} text={row => `${changeLabel(row.change_type, t)}: ${row.description}`} materials={materials} versionId={version.id} target={citeTarget} />
      </div>
      <section data-testid="brief-materials" className="flex min-w-0 flex-col gap-2">
        <h3 className="flex items-baseline gap-2 text-small font-medium text-ink">{t("纳入简报的材料")}<span className="font-mono text-caption font-normal text-muted-foreground">{materials.length} {locale === "en-US" ? t("份材料") : "份"}</span></h3>
        {materials.length === 0
          ? <p className="text-small text-muted-foreground">{t("此简报没有引用已成功分析的材料。")}</p>
          : <ol className="m-0 flex list-none flex-col gap-2 p-0">
            {materials.map((material, index) => <li key={material.analysis_id}>
              <OpinionFacts className="gap-1 pr-12 relative">
                <span className="material-fact-source" aria-hidden="true">[{index + 1}]</span>
                <strong className="text-body font-medium text-ink [overflow-wrap:anywhere]">{material.title || sourceTypeLabel(material.source_type, locale)}</strong>
                <span className="text-caption text-muted-foreground">{sourceTypeLabel(material.source_type, locale)} · {t("发布时间")} {day(material.published_at)} · {t("观察时间")} {day(material.observed_at)}</span>
                {(material.coverage_incomplete || material.truncated || (material.source_type === "uploaded_media" && material.user_rating_label)) && <span className="text-caption text-muted-foreground">{material.source_type === "uploaded_media" && material.user_rating_label ? `${material.user_rating_label} · ` : ""}{material.coverage_incomplete || material.truncated ? t("仅覆盖部分材料") : ""}</span>}
                {material.analysis_summary && <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{t("分析摘要")}: {material.analysis_summary}</span>}
                {material.key_numbers?.length ? <span className="text-caption text-muted-foreground" title={material.key_numbers.flatMap(item => item.citations.map(citation => citation.quote)).join("\n")}>{t("关键数字")}: {material.key_numbers.map(item => `${item.name} ${item.value_text}${item.period ? ` (${item.period})` : ""}`).join(" · ")}</span> : null}
                <span className="-ml-2 flex flex-wrap gap-x-1">
                  {citeTarget === "evidence" && <Link to={paths.evidence(version.id, material.source_type, material.source_id)} className="inline-flex h-8 items-center rounded-sm px-2 text-small font-medium text-brand outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">{t("在证据页打开")}</Link>}
                  {material.source_url && <a href={material.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center rounded-sm px-2 text-small font-medium text-brand outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">{t("原始来源")}</a>}
                  <Link to={paths.materials({ symbol: material.symbol, focus: material.source_id, type: material.source_type, analysis: material.analysis_id })} className="inline-flex h-8 items-center rounded-sm px-2 text-small font-medium text-brand outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">{t("查看这版分析")}</Link>
                </span>
              </OpinionFacts>
            </li>)}
          </ol>}
      </section>
      {brief.omitted.length > 0 && <details className="rounded-md border border-line bg-sunken">
        <summary className="cursor-pointer px-3 py-2 text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("未纳入材料")} ({brief.omitted.length})</summary>
        <ul className="m-0 flex list-none flex-col gap-1 px-3 pb-2 text-small text-ink-2">{brief.omitted.map((row, index) => <li key={`${row.source_type}:${row.source_id}:${index}`}>{sourceTypeLabel(row.source_type, locale)} · {row.reason}</li>)}</ul>
      </details>}
      <p className="text-caption text-muted-foreground">{t(copy.briefNote)}</p>
    </div>
  </OpinionCard>;
}
