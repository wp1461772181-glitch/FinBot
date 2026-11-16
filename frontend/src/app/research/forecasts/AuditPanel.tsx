import { useEffect, useState } from "react";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import { getV2Job } from "../../../api/forecast-v2";
import type { V2ForecastJob, V2Timeline, V2TimelineEntry, V2VersionDetail } from "../../../types";
import { NOT_RECORDED, hasDecisionProbabilities, recordedModel } from "../../../forecast-model.mjs";
import { sourceDiff } from "../../../forecast-detail.mjs";
import { evidenceTitle, processingStatus, sourceKey } from "../../../EvidenceProcessing";
import { asRecord, asText, modelStatusText } from "../../../ForecastShared";
import { translatePhrase, useLocale } from "../../../i18n";
import { day } from "./format";

type Row = { label: string; value: string };

/** What the audit rows read from one saved version: raw values as stored, 未记录 when the version has none. */
function auditRows(version: V2VersionDetail): Row[] {
  const manifest = asRecord(version.model_manifest);
  const decision = asRecord(manifest.decision_provider);
  const { provider, actual_model, requested_model } = recordedModel(version);
  const rows: Row[] = [
    { label: "服务方", value: provider ?? NOT_RECORDED },
    { label: "请求模型", value: requested_model ?? NOT_RECORDED },
    { label: "实际返回模型", value: actual_model ?? NOT_RECORDED },
    { label: "问题版本", value: asText(decision.question_version) ?? NOT_RECORDED },
    { label: "请求编号", value: asText(decision.request_id) ?? NOT_RECORDED },
    { label: "输入哈希", value: asText(decision.input_sha256) ?? NOT_RECORDED },
    { label: "任务编号", value: version.job_id },
  ];
  // A retired control run stays a record like any other; its manifest keys are shown raw, not dressed up.
  if (manifest.hidden_control !== undefined || manifest.control_of_root_id !== undefined) {
    rows.push({ label: "对照记录", value: JSON.stringify({ hidden_control: manifest.hidden_control ?? null, control_of_root_id: manifest.control_of_root_id ?? null }) });
  }
  return rows;
}

const sourceIdentity = (item: Record<string, unknown>) => `${String(item.source_type ?? "unknown")}:${String(item.source_id ?? item.event_version_id ?? item.id ?? "")}`;
const shortHash = (value: unknown) => { const text = String(value ?? "—"); return text.length > 14 ? `${text.slice(0, 12)}…` : text; };
const coverageText = (value: unknown) => translatePhrase(value === true ? "覆盖不完整" : value === false ? "覆盖状态已记录" : "覆盖状态未知");
const triggerTypeText = (value: unknown) => translatePhrase(value === "manual_revision" ? "人工发起修订" : value === "automatic_monitor" ? "监控发现材料" : value === "new_forecast" ? "新建预测" : "预测更新");
const discoveryKindText = (value: unknown) => translatePhrase(value === "official_scan" ? "官方资料扫描发现" : value === "manual_selection" ? "人工选择" : value === "uploaded" ? "上传材料" : "来源记录");
function researchStatusText(value: unknown) {
  switch (value) {
    case "ready": case "succeeded": return translatePhrase("研究已就绪");
    case "failed": case "failed_before_run": return translatePhrase("研究失败");
    case "not_run": return translatePhrase("未运行研究");
    case "no_eligible_frozen_sources": return translatePhrase("没有合规保存来源");
    default: return translatePhrase("研究状态未记录");
  }
}
function explicitSourceKeys(report: Record<string, unknown> | null): Set<string> {
  const refs = (report?.automatic_selection as { explicit_source_refs?: unknown } | undefined)?.explicit_source_refs;
  if (!Array.isArray(refs)) return new Set();
  return new Set(refs.flatMap(ref => {
    const value = ref as { source_type?: unknown; source_id?: unknown } | null;
    return value && typeof value.source_type === "string" && typeof value.source_id === "string" ? [`${value.source_type}:${value.source_id}`] : [];
  }));
}
function changeReasonText(reason: string, locale: "zh-CN" | "en-US") {
  if (reason === "new forecast with frozen observed market and evidence inputs") return locale === "en-US" ? "New forecast using a frozen snapshot of the available market data and sources." : "新建预测：冻结当时可用的行情和来源快照。";
  const revision = reason.match(/^(manual_revision|automatic_revision): inherited frozen evidence plus (\d+) new or changed observed event\(s\)$/);
  if (!revision) return reason;
  const count = Number(revision[2]);
  if (locale === "en-US") return `${revision[1] === "manual_revision" ? "Manual revision" : "Automatic revision"}: carried forward the prior frozen sources and added ${count} new or changed observed ${count === 1 ? "event" : "events"}.`;
  return `${revision[1] === "manual_revision" ? "人工修订" : "自动修订"}：继承原冻结来源，并新增或更新了 ${count} 项可观察事件。`;
}

function Rows({ rows }: { rows: Row[] }) {
  const { t } = useLocale();
  return <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-small">
    {rows.map(row => <div key={row.label} className="contents"><dt className="text-muted-foreground">{t(row.label)}</dt><dd className="m-0"><code className="font-mono text-caption text-ink [overflow-wrap:anywhere]">{row.value}</code></dd></div>)}
  </dl>;
}

/** 版本事件 (the old version records): every version of the chain, how it began, its model status and probabilities, and the reason it was made. */
function VersionEvents({ versions, selectedId, onSelect }: { versions: V2TimelineEntry[]; selectedId: string; onSelect: (id: string) => void }) {
  const { t, locale } = useLocale();
  return <section data-testid="forecast-events" aria-labelledby="events-title" className="flex min-w-0 flex-col gap-2">
    <div className="flex items-baseline gap-3"><h3 id="events-title" className="text-title-s text-ink">{t("预测版本记录")}</h3><span className="text-caption text-muted-foreground">{t("同一固定目标")}</span></div>
    <ol className="m-0 flex list-none flex-col gap-2 p-0">
      {versions.map(version => <li key={version.id} data-selected={version.id === selectedId ? "" : undefined}>
        <button type="button" onClick={() => onSelect(version.id)} aria-current={version.id === selectedId ? "true" : undefined}
          className={cn("flex w-full min-w-0 flex-col gap-1.5 rounded-md border px-3 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring", version.id === selectedId ? "border-brand bg-brand-soft" : "border-line bg-surface hover:bg-sunken")}>
          <strong className="text-small font-medium text-ink">{t("第")} {version.version_no} {t("版")} · {t(version.parent_version_id ? "修订版本" : "初始版本")}</strong>
          <span className="text-caption text-muted-foreground [overflow-wrap:anywhere]">{day(version.decision_at)} · {modelStatusText(version.model_status)} · {triggerTypeText(version.trigger_type)}</span>
          {version.change_reason && <span className="text-caption text-ink-2 [overflow-wrap:anywhere]">{changeReasonText(version.change_reason, locale)}</span>}
          {hasDecisionProbabilities(version.model_status) && version.decision_probabilities && <ProbabilityBar probabilities={version.decision_probabilities} size="mini" focusable={false} className="max-w-xs" />}
          {version.model_status === "experimental_joint" && version.joint_probabilities && <ProbabilityBar probabilities={version.joint_probabilities} size="mini" focusable={false} className="max-w-xs" />}
        </button>
      </li>)}
    </ol>
  </section>;
}

/** 所选版本的来源差异: what the frozen list changed against the parent, the market inputs, and every source with what became of it in the brief. */
function SourceDetail({ current, parent }: { current: V2VersionDetail; parent: V2VersionDetail | undefined }) {
  const { t, locale } = useLocale();
  const countLabel = (count: number) => locale === "en-US" ? `${count} ${count === 1 ? "material" : "materials"}` : `${count} ${t("条")}`;
  const sources = current.evidence_version_manifest;
  const diff = sourceDiff(current, parent ?? null);
  const parentKeys = new Set((parent?.evidence_version_manifest ?? []).map(sourceIdentity));
  const explicit = explicitSourceKeys(current.research_report);
  const explicitCount = sources.filter(item => explicit.has(sourceIdentity(item))).length;
  const addedItems = sources.filter(item => !parentKeys.has(sourceIdentity(item)));
  const automaticAdded = addedItems.filter(item => !explicit.has(sourceIdentity(item))).length;
  const market = current.price_input_manifest;
  const brief = current.research_brief ?? null;
  const included = new Set((brief?.material_refs ?? []).map(sourceKey));
  const includedCount = sources.filter(item => included.has(sourceKey(item))).length;
  const status = researchStatusText(current.research_report?.research_conclusions_status ?? current.research_report?.status);
  return <section data-testid="forecast-sources" aria-label={t("所选版本的保存的输入")} className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-col gap-1">
      <p className="text-caption font-medium text-muted-foreground">{t("所选第")} {current.version_no} {t("版的来源差异")}</p>
      <h3 className="text-title-s text-ink">{parent ? `${t("新增")} ${diff.added} · ${t("状态替换")} ${diff.replaced} · ${t("移除")} ${diff.removed} · ${t("继承")} ${diff.inherited}` : locale === "en-US" ? `Frozen candidates: ${countLabel(sources.length)}` : `${t("冻结候选")} ${countLabel(sources.length)}`}</h3>
      <p className="text-small text-ink-2">{parent ? locale === "en-US" ? `Source composition: ${countLabel(diff.inherited)} inherited from the parent, ${countLabel(explicitCount)} manually selected, and ${countLabel(automaticAdded)} automatically added by the system.` : `${t("本版来源构成：父版继承")} ${diff.inherited} ${t("条，人工选入")} ${explicitCount} ${t("条，系统自动新增")} ${automaticAdded} ${t("条。")}` : t("初始版本没有父版本可比较。")}</p>
    </div>
    <div className="flex flex-col gap-0.5">
      <strong className="text-small font-medium text-ink">{brief ? locale === "en-US" ? `Actually cited in the brief: ${countLabel(includedCount)}` : `${t("简报实际引用")} ${countLabel(includedCount)}` : t("该版本未保存简报引用")}</strong>
      <span className="text-caption text-muted-foreground">{brief ? locale === "en-US" ? `Not included in the brief: ${countLabel(Math.max(0, sources.length - includedCount))}. The frozen list records candidate sources available at the time; it does not mean every source was analyzed or entered the brief.` : `${t("未进入简报")} ${countLabel(Math.max(0, sources.length - includedCount))}。冻结清单记录当时的候选来源，不表示这些来源都被分析或进入了简报。` : t("没有简报记录时，无法从此版本确认哪些材料完成了分析。")}</span>
    </div>
    <Rows rows={[
      { label: "行情数据截止", value: day(String(market.market_cutoff_at ?? current.market_cutoff_at)) },
      { label: "最近完整交易日", value: String(market.latest_completed_session ?? "未记录") },
      { label: "价格输入哈希", value: shortHash(market.price_input_sha256) },
      { label: "研究报告", value: status },
    ]} />
    {sources.length === 0 ? <p className="text-small text-muted-foreground">{t("这个版本没有保存合规证据来源。")}</p>
      : <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {sources.map((item, index) => {
          const url = typeof item.source_url === "string" ? item.source_url : null;
          const key = sourceIdentity(item);
          const processing = processingStatus(item, brief, t);
          const origin = explicit.has(key) ? t("人工选入") : parent && parentKeys.has(key) ? (item.is_new ? t("系统记录状态变化") : t("从父版继承")) : parent ? t("系统自动纳入") : t("初始预测自动纳入");
          const published = item.published_at ?? item.public_at;
          return <li key={`${String(item.event_version_id ?? item.id ?? key)}-${index}`} className="material-fact flex min-w-0 flex-col gap-1 px-3 py-2">
            <strong className="text-small font-medium text-ink [overflow-wrap:anywhere]">{evidenceTitle(item, brief?.material_refs.find(ref => sourceKey(ref) === sourceKey(item)))}</strong>
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">{day(typeof published === "string" ? published : null)} · {coverageText(item.coverage_incomplete)}
              <StatusBadge kind={processing.tone === "included" ? "success" : "neutral"} className="h-5">{processing.label}</StatusBadge></span>
            <span className="text-caption text-muted-foreground">{processing.detail}</span>
            <span className="text-caption text-muted-foreground">{origin} · {t(item.is_new ? "本版本新增/状态变更" : "从父版继承")} · {discoveryKindText(item.discovery_kind)}</span>
            {url ? <a href={url} target="_blank" rel="noopener noreferrer" className="w-fit text-small font-medium text-brand underline-offset-2 hover:underline">{t("打开原始来源")}</a> : <span className="text-caption text-muted-foreground">{t("原始来源链接未记录")}</span>}
          </li>;
        })}
      </ul>}
  </section>;
}

/**
 * 审计与来源 (the old 审计 and 版本事件): who decided and how (the saved request, raw), the job's state (read when this tab is opened), the version
 * records, the source differences with the brief's treatment of each source, and the raw model manifest, collapsed.
 */
export function AuditPanel({ timeline, current, parent, selectedId, onSelect }: { timeline: V2Timeline; current: V2VersionDetail | undefined; parent: V2VersionDetail | undefined; selectedId: string; onSelect: (id: string) => void }) {
  const { t } = useLocale();
  const [job, setJob] = useState<{ kind: "loading" } | { kind: "ready"; data: V2ForecastJob } | { kind: "error" } | null>(null);
  const jobId = current?.job_id ?? null;
  useEffect(() => {
    if (!jobId) { setJob(null); return; }
    const controller = new AbortController();
    setJob({ kind: "loading" });
    getV2Job(jobId, controller.signal)
      .then(next => { if (!controller.signal.aborted) setJob({ kind: "ready", data: next }); })
      .catch(() => { if (!controller.signal.aborted) setJob({ kind: "error" }); });
    return () => controller.abort();
  }, [jobId]);
  const jobText = job?.kind === "ready" ? `${job.data.status}${job.data.error?.type ? ` · ${job.data.error.type}` : ""} · ${job.data.current_stage}` : job?.kind === "error" ? NOT_RECORDED : "…";
  return <div data-testid="forecast-audit" className="flex min-w-0 flex-col gap-6">
    {current && <section aria-label={t("审计与来源")} className="flex min-w-0 flex-col gap-2">
      <Rows rows={[...auditRows(current), { label: "任务状态", value: jobText }]} />
    </section>}
    <VersionEvents versions={timeline.versions} selectedId={selectedId} onSelect={onSelect} />
    {current && <SourceDetail current={current} parent={parent} />}
    {current && <details className="rounded-md border border-line bg-sunken">
      <summary className="cursor-pointer px-3 py-2 text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("模型清单（原始）")}</summary>
      <pre className="m-0 max-h-96 overflow-auto px-3 pb-3 font-mono text-caption text-ink-2">{JSON.stringify(current.model_manifest, null, 2)}</pre>
    </details>}
  </div>;
}
