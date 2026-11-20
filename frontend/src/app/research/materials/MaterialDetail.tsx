import { useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonCard } from "@/components/state/Skeleton";
import { StatefulButton } from "@/components/state/StatefulButton";
import { StatusBadge } from "@/components/StatusBadge";
import { ApiError, getChatMode } from "../../../api/base";
import { getModelCatalog } from "../../../api/bots";
import type { CatalogModel } from "../../../api/bots";
import { createMaterialAnalysisJob, getMaterialAnalysis, getMaterialAnalysisHistory, getMaterialAnalysisSettings } from "../../../api/material-library";
import { fetchFilingContent } from "../../../api/market-data";
import type { MaterialAnalysisJob, MaterialAnalysisVersion, MaterialCitation, MaterialItem } from "../../../types";
import { translatePhrase, useLocale } from "../../../i18n";
import { useAiContentLocalization, withLocalizedFields } from "../../../useAiContentLocalization";
import { httpsUrl } from "../evidence/evidence-model.mjs";
import { AnalysisView, formatDate } from "./AnalysisView";
import { DetailTabs } from "./DetailTabs";
import { HistoryView, type Load } from "./HistoryView";
import { OriginalView, type CitationSelection } from "./OriginalView";
import { followMaterialJob, onMaterialJobSettled } from "./material-jobs";
import { PENDING_JOB, isActiveJobStatus, jobErrorPhrase } from "./materials-model.mjs";

type DetailTab = "analysis" | "original" | "history";
const DEFAULT_MODEL = "__default";

function actionMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) return translatePhrase(error.status === 402 ? "模型服务余额或账单状态需要处理后再试。" : error.status === 429 ? "模型服务暂时限流，请稍后重试。" : error.message);
  return translatePhrase(fallback);
}

/**
 * One material (design 4.7): its heading, then three tabs.  AI 分析 is the opinion material (AnalysisView), with the one-time model choice and the button that
 * starts (or repeats) the analysis; 原始材料 is the fact material; 分析历史 lists the saved versions.  A job that is under way is on the task bar (material-jobs.ts);
 * this view hears when it settles.  `initialAnalysisId` is the version an address named.  The reads and the requests are the old page's.
 */
export function MaterialDetail({ material, initialAnalysisId = null, onUpdated }: { material: MaterialItem; initialAnalysisId?: string | null; onUpdated: () => void }) {
  const { locale, t } = useLocale();
  const [tab, setTab] = useState<DetailTab>("analysis");
  const [analysisId, setAnalysisId] = useState<string | null>(material.latest_analysis_id);
  const [focusedAnalysisId, setFocusedAnalysisId] = useState<string | null>(initialAnalysisId);
  const [analysis, setAnalysis] = useState<Load<MaterialAnalysisVersion>>({ kind: "idle" });
  const [history, setHistory] = useState<Load<MaterialAnalysisVersion[]>>({ kind: "idle" });
  const [originalFetch, setOriginalFetch] = useState<"idle" | "loading">("idle");
  const [job, setJob] = useState<MaterialAnalysisJob | null>(material.latest_job);
  const [actionError, setActionError] = useState<string | null>(null);
  const [citation, setCitation] = useState<CitationSelection>(null);
  // The per-analysis model is a server catalog entry; "" is the material-analysis default (the one set in 设置).
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([]);
  const [catalogName, setCatalogName] = useState("");
  const [defaultModel, setDefaultModel] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const sequence = useRef(0);
  const startedAt = useRef(0);
  const onUpdatedRef = useRef(onUpdated);
  onUpdatedRef.current = onUpdated;

  useEffect(() => { setFocusedAnalysisId(initialAnalysisId); }, [initialAnalysisId, material.source_type, material.source_id]);

  useEffect(() => {
    if (getChatMode() !== "personal") return;
    let cancelled = false;
    getModelCatalog()
      .then(catalog => { if (!cancelled) setCatalogModels(catalog.models.filter(entry => entry.key_status === "configured")); })
      .catch((error: unknown) => { if (!cancelled) setProfileError(error instanceof Error ? error.message : "模型目录暂时无法读取。"); });
    getMaterialAnalysisSettings().then(settings => { if (!cancelled) setDefaultModel(settings.model); }).catch(() => { /* The default is only shown when it can be read. */ });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const mine = ++sequence.current;
    const selected = focusedAnalysisId ?? material.latest_analysis_id;
    startedAt.current = mine;
    setAnalysisId(selected);
    setJob(material.latest_job);
    setAnalysis(selected ? { kind: "loading" } : { kind: "idle" });
    setHistory({ kind: "idle" });
    setOriginalFetch("idle");
    setActionError(null);
    setCitation(null);
    if (material.latest_job) followMaterialJob(material.latest_job, { sourceType: material.source_type, sourceId: material.source_id, title: material.title });
    if (selected) {
      getMaterialAnalysis(selected, controller.signal)
        .then(value => { if (!controller.signal.aborted && mine === sequence.current) setAnalysis({ kind: "ready", value }); })
        .catch((error: unknown) => { if (!controller.signal.aborted && mine === sequence.current) setAnalysis({ kind: "error", message: actionMessage(error, "暂时无法读取这版分析。") }); });
    }
    return () => { controller.abort(); sequence.current += 1; };
  }, [material.source_type, material.source_id, material.latest_analysis_id, focusedAnalysisId]);

  // The end of this material's job: the saved analysis is shown (unless the reader moved to another version meanwhile), a failure says why, the list is read again.
  useEffect(() => onMaterialJobSettled(event => {
    if (event.sourceType !== material.source_type || event.sourceId !== material.source_id) return;
    setJob(event.job);
    if (event.analysis && event.job.analysis_id && startedAt.current === sequence.current) { setAnalysisId(event.job.analysis_id); setAnalysis({ kind: "ready", value: event.analysis }); }
    if (event.job.status === "failed" || event.job.status === "blocked_data") setActionError(translatePhrase(jobErrorPhrase(event.job.safe_error_code)));
    onUpdatedRef.current();
  }), [material.source_type, material.source_id]);

  useEffect(() => {
    if (tab !== "history") return;
    const controller = new AbortController();
    setHistory({ kind: "loading" });
    getMaterialAnalysisHistory(material.source_type, material.source_id, controller.signal)
      .then(result => { if (!controller.signal.aborted) setHistory({ kind: "ready", value: result.items }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setHistory({ kind: "error", message: actionMessage(error, "暂时无法读取分析历史。") }); });
    return () => controller.abort();
  }, [tab, material.source_type, material.source_id]);

  async function startAnalysis(force: boolean) {
    setFocusedAnalysisId(null);
    setActionError(null);
    setJob(PENDING_JOB);
    const about = { sourceType: material.source_type, sourceId: material.source_id, title: material.title };
    try {
      const created = await createMaterialAnalysisJob(material.source_type, material.source_id, force, catalogName ? { catalog_model: catalogName } : undefined);
      setJob(created);
      startedAt.current = sequence.current;
      if (created.status === "succeeded" && created.analysis_id) {
        setAnalysisId(created.analysis_id);
        setAnalysis({ kind: "ready", value: await getMaterialAnalysis(created.analysis_id) });
        onUpdated();
      } else if (created.status === "blocked_data") {
        setActionError(t("这份材料目前没有可分析的正文。请先读取 SEC 原文，或核对已上传文件。"));
        onUpdated();
      } else followMaterialJob(created, about);
    } catch (error) {
      setJob(material.latest_job);
      setActionError(actionMessage(error, "提交分析任务失败。"));
      throw error;
    }
  }

  async function fetchOriginal() {
    if (material.source_type !== "official_filing") return;
    setOriginalFetch("loading");
    setActionError(null);
    try {
      const accession = material.title.split(" ").slice(1).join(" ");
      await fetchFilingContent(material.symbol, accession);
    } catch (error) { setActionError(actionMessage(error, "读取 SEC 原文失败。请打开来源网站核对状态。")); }
    finally { setOriginalFetch("idle"); onUpdated(); }
  }

  async function openHistoryVersion(id: string) {
    const mine = ++sequence.current;
    setAnalysisId(id);
    setCitation(null);
    setAnalysis({ kind: "loading" });
    setTab("analysis");
    try {
      const value = await getMaterialAnalysis(id);
      if (mine === sequence.current) setAnalysis({ kind: "ready", value });
    } catch (error) { if (mine === sequence.current) setAnalysis({ kind: "error", message: actionMessage(error, "暂时无法读取选中的历史版本。") }); }
  }

  function locateCitation(item: MaterialCitation) {
    if (!item.quote.trim() || analysis.kind !== "ready") return;
    setCitation({ quote: item.quote, analysisVersion: analysis.value.version_no });
    setTab("original");
  }

  const selectedAnalysis = analysis.kind === "ready" ? analysis.value : null;
  const localization = useAiContentLocalization("material_analysis", selectedAnalysis?.analysis_id);
  const displayed = selectedAnalysis && localization.kind === "ready" ? { ...selectedAnalysis, payload: withLocalizedFields(selectedAnalysis.payload, localization.fields) } : selectedAnalysis;
  const busy = Boolean(job && isActiveJobStatus(job.status));
  const canAnalyze = material.can_view_original;
  const cachedInvalidOutput = job?.status === "failed" && job.safe_error_code === "invalid_model_output";
  const sourceLink = httpsUrl(material.source_url);
  const repeat = Boolean(selectedAnalysis);
  const label = busy ? t("任务处理中…") : repeat ? t("重新分析") : cachedInvalidOutput ? t("跳过失败记录并重新分析") : t("开始分析");
  const modelName = (entry: CatalogModel) => `${entry.display_name || entry.name} · ${entry.model}`;

  return <section data-testid="material-detail" data-source-id={material.source_id} aria-label={`${material.title} ${t("详情")}`} className="flex min-w-0 flex-col gap-3">
    <header className="flex min-w-0 flex-col gap-1">
      <p className="text-caption text-muted-foreground">{t(material.source_type === "official_filing" ? "SEC 官方材料" : "用户上传材料")} · {material.symbol}</p>
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <h2 data-testid="material-title" className="min-w-0 flex-1 text-title-s text-ink [overflow-wrap:anywhere] mb-3">{material.title}</h2>
        {sourceLink && <Button asChild variant="outline" size="sm" className="max-sm:h-11"><a href={sourceLink} target="_blank" rel="noopener noreferrer">{t("打开来源")}<ExternalLink aria-hidden="true" /></a></Button>}
      </div>
      <p className="text-caption text-muted-foreground">{t("发布")} {formatDate(material.published_at, locale)} · {t("发现")} {formatDate(material.observed_at, locale)}</p>
    </header>
    <div className="flex min-w-0 flex-col gap-3">
      <DetailTabs value={tab} label={t("材料详情")} panelId="material-panel" onChange={value => { if (value === "original") setCitation(null); setTab(value); }}
        tabs={[{ id: "analysis", label: t("AI 分析"), testid: "material-tab-analysis" }, { id: "original", label: t("原始材料"), testid: "material-tab-original" }, { id: "history", label: t("分析历史"), testid: "material-tab-history" }]} />
      {actionError && <ErrorBar message={actionError} />}
      <div id="material-panel" role="tabpanel" aria-labelledby={`material-tab-${tab}`} className="flex min-w-0 flex-col gap-3">
      {tab === "analysis" && <>
        {canAnalyze && <div data-testid="analysis-toolbar" className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex min-w-0 items-center gap-2">
            <span id="analysis-model-label" className="shrink-0 text-small text-muted-foreground">{t("分析模型")}</span>
            <Select value={catalogName || DEFAULT_MODEL} onValueChange={value => setCatalogName(value === DEFAULT_MODEL ? "" : value)} disabled={busy}>
              <SelectTrigger size="sm" data-testid="analysis-model" aria-labelledby="analysis-model-label" className="max-w-64 max-sm:h-11"><SelectValue /></SelectTrigger>
              <SelectContent position="popper">
                <SelectItem value={DEFAULT_MODEL}>{t("系统默认（后台配置）")}</SelectItem>
                {catalogModels.map(entry => <SelectItem key={entry.name} value={entry.name}>{modelName(entry)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <StatefulButton type="button" data-testid="analysis-start" data-mode={repeat ? "reanalyze" : "start"} variant={repeat ? "outline" : "default"} size="sm" disabled={busy} className="max-sm:h-11"
            onClick={() => startAnalysis(repeat ? true : cachedInvalidOutput)} onError={() => { /* The message is on the page. */ }}>{label}</StatefulButton>
          {catalogName
            ? <small className="basis-full text-caption text-muted-foreground">{t("仅本次分析使用；默认模型在 Agent 管理页配置。")}</small>
            : defaultModel && <small data-testid="analysis-default-model" className="basis-full font-mono text-caption text-muted-foreground">{t("默认模型")} · {defaultModel}</small>}
          {profileError && <small className="basis-full text-caption text-muted-foreground">{profileError}</small>}
        </div>}
        {busy && <p data-testid="analysis-job" role="status" className="flex items-center gap-2 text-small text-ink-2"><StatusBadge kind="progress">{t("分析中")}</StatusBadge>{job?.status === "queued" ? t("分析任务排队中…") : t("正在分析这份材料…")}</p>}
        {job && (job.status === "failed" || job.status === "blocked_data") && <p role="status" className="text-small text-muted-foreground">{t("最近一次分析尝试")}{job.status === "failed" ? t("失败") : t("暂不可执行")}（{translatePhrase(jobErrorPhrase(job.safe_error_code))}）。{t("如有既有成功版本，仍可在此查看。")}</p>}
        {analysis.kind === "loading" && <DelayedSkeleton><SkeletonCard /></DelayedSkeleton>}
        {analysis.kind === "error" && <ErrorBar message={analysis.message} />}
        {displayed && <AnalysisView analysis={displayed} onLocateCitation={locateCitation} />}
        {locale === "en-US" && localization.kind === "loading" && <p role="status" className="text-caption text-muted-foreground">{t("Translating saved AI analysis…")}</p>}
        {locale === "en-US" && localization.kind === "error" && <p role="status" className="text-caption text-muted-foreground">{t("English translation is temporarily unavailable; showing the saved original.")}</p>}
        {!selectedAnalysis && analysis.kind !== "loading" && canAnalyze && <EmptyState title={cachedInvalidOutput ? t("上次分析未通过校验") : t("这份材料还没有成功的分析版本")} description={cachedInvalidOutput ? t("这次失败结果被暂存了。重新分析会跳过该失败记录，再请求 DeepSeek；不会删除其他成功版本。") : t("分析会引用本次冻结的材料文本。保存后重新打开可直接查看，不会重复调用模型。")} className="rounded-md border border-dashed border-line" />}
        {!canAnalyze && material.source_type === "official_filing" && <EmptyState title={t("SEC 目录记录还没有可分析的正文")} description={t("读取 SEC 正文后才能运行分析；也可以在“原始材料”页直接打开来源网站阅读。")} className="rounded-md border border-dashed border-line">
          <Button type="button" size="sm" disabled={busy || originalFetch === "loading"} onClick={() => { void fetchOriginal(); }} className="mt-2">{originalFetch === "loading" ? t("正在读取 SEC 正文…") : t("读取 SEC 正文供 AI 分析")}</Button>
        </EmptyState>}
        {!canAnalyze && material.source_type !== "official_filing" && <EmptyState title={t("这份上传材料暂无可分析正文")} description={t("可以在“原始材料”页打开来源链接核对。")} className="rounded-md border border-dashed border-line" />}
      </>}
      {tab === "original" && <OriginalView material={material} citation={citation} />}
      {tab === "history" && <HistoryView state={history} selectedAnalysisId={analysisId} onSelect={id => { void openHistoryVersion(id); }} />}
      </div>
    </div>
  </section>;
}
