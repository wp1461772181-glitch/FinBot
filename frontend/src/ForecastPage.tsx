import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Tx, useLocale } from "./i18n";
import { ApiError } from "./api/base";
import { createV2ManualRevisionJob, getV2Evaluations, getV2ForecastVersion, getV2Job, getV2RevisionCandidates, getV2Timeline } from "./api/forecast-v2";
import { getV2Prices } from "./api/prices";
import type { V2RevisionCandidates } from "./api/forecast-v2";
import type { PriceHistory, V2EvaluationResponse, V2ForecastJob, V2ForecastRoot, V2ForecastRoots, V2Timeline, V2VersionDetail } from "./types";
import { hasDecisionProbabilities } from "./forecast-model.mjs";
import { hashHref, paths } from "./routes.mjs";
import { ForecastVersionHeader } from "./ForecastVersionHeader";
import { ForecastSummary } from "./ForecastSummary";
import { ForecastPriceContextChart } from "./ForecastPriceChart";
import { ResearchBriefView } from "./ResearchBriefView";
import { EvidenceEvents, RevisionComparison } from "./ForecastTimeline";
import { ForecastRevisionForm } from "./ForecastRevisionForm";
import { EvaluationReadout } from "./ForecastEvaluationReadout";
import { ForecastAudit } from "./ForecastAudit";
import { JobStatus, errorMessage, isActiveJob } from "./ForecastJob";
import type { ResourceState } from "./ForecastShared";

type Details = ResourceState<{ current: V2VersionDetail; parent: V2VersionDetail | null }>;

// 查看完整分析: the library opens on the cited material and its analysis (the address carries them).
const materialAnalysisPath = (material: { symbol: string; source_type: string; source_id: string; analysis_id: string }) => paths.materials({ symbol: material.symbol, focus: material.source_id, type: material.source_type, analysis: material.analysis_id });

/** A fixed target date counts as expired once it is before today (UTC); the server still decides what may be revised. */
function expiredFromTarget(target: unknown): boolean | null {
  if (typeof target !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(target)) return null;
  return target < new Date().toISOString().slice(0, 10);
}

/**
 * `#forecast/<rootId>`: one forecast, top to bottom (design §1.2 Level 2).  It merges the old 工作台 and 修订
 * views, which were two views of the same record.  The company comes from the root itself, never from a picker,
 * and a root that cannot be read is reported as such; no other forecast ever stands in for it.
 */
export function ForecastPage({ rootId, versionId, reviseSourceId, focusVersions = false, onHome }: { rootId: string; versionId?: string; reviseSourceId?: string; focusVersions?: boolean; onHome: () => void }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const reviseApplied = useRef(false);
  const [timeline, setTimeline] = useState<ResourceState<V2Timeline>>({ kind: "loading" });
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedVersionId, setSelectedVersionId] = useState(versionId ?? "");
  const [details, setDetails] = useState<Details | null>(null);
  const [evaluations, setEvaluations] = useState<ResourceState<V2EvaluationResponse>>({ kind: "loading" });
  const [priceHistory, setPriceHistory] = useState<PriceHistory | null>(null);
  const [activeJob, setActiveJob] = useState<V2ForecastJob | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [parentVersionId, setParentVersionId] = useState("");
  const [selectedSourceKeys, setSelectedSourceKeys] = useState<string[]>([]);
  const [revisionCandidates, setRevisionCandidates] = useState<ResourceState<V2RevisionCandidates> | null>(null);

  useEffect(() => { setSelectedVersionId(versionId ?? ""); }, [rootId, versionId]);

  useEffect(() => {
    const controller = new AbortController();
    setTimeline({ kind: "loading" });
    setNotFound(false);
    getV2Timeline(rootId, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setTimeline({ kind: "ready", data: next }); })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && (error.status === 404 || error.status === 422)) setNotFound(true);
        setTimeline({ kind: "error", message: errorMessage(error, "无法读取所选预测的版本链。") });
      });
    return () => controller.abort();
  }, [rootId, reloadKey]);

  const versions = useMemo(() => timeline.kind === "ready" ? timeline.data.versions : [], [timeline]);
  const symbol = timeline.kind === "ready" ? timeline.data.symbol : null;

  useEffect(() => {
    if (!versions.length) { setDetails(null); return; }
    if (!versions.some((version) => version.id === selectedVersionId)) setSelectedVersionId(versions.at(-1)!.id);
  }, [versions, selectedVersionId]);

  useEffect(() => {
    if (!selectedVersionId || !versions.some((version) => version.id === selectedVersionId)) return;
    const controller = new AbortController();
    setDetails({ kind: "loading" });
    getV2ForecastVersion(selectedVersionId, controller.signal)
      .then(async (current) => {
        const parent = current.parent_version_id ? await getV2ForecastVersion(current.parent_version_id, controller.signal) : null;
        if (!controller.signal.aborted) setDetails({ kind: "ready", data: { current, parent } });
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setDetails({ kind: "error", message: errorMessage(error, "无法读取冻结版本详情。") }); });
    return () => controller.abort();
  }, [selectedVersionId, versions]);

  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    setEvaluations({ kind: "loading" });
    getV2Evaluations(symbol, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setEvaluations({ kind: "ready", data: next }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setEvaluations({ kind: "error", message: errorMessage(error, "暂时无法读取到期评估。") }); });
    getV2Prices(symbol, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setPriceHistory(next.price_history); })
      .catch(() => { if (!controller.signal.aborted) setPriceHistory(null); });
    return () => controller.abort();
  }, [symbol, reloadKey]);

  // The 修订 action opens the section for a #revisions link.
  useEffect(() => {
    if (focusVersions && timeline.kind === "ready") document.getElementById("forecast-versions")?.scrollIntoView?.();
  }, [focusVersions, timeline.kind]);

  useEffect(() => {
    if (activeJob === null || !isActiveJob(activeJob)) return;
    const jobId = activeJob.id;
    const timer = window.setInterval(() => {
      getV2Job(jobId)
        .then((next) => {
          setActiveJob(next);
          if (!isActiveJob(next)) setReloadKey((value) => value + 1);
        })
        .catch((error: unknown) => setActionError(errorMessage(error, "无法刷新预测任务状态。")));
    }, 3_000);
    return () => window.clearInterval(timer);
  }, [activeJob]);

  const chosenVersion = versions.find((version) => version.id === parentVersionId) ?? versions.at(-1);
  const chosenVersionId = chosenVersion?.id ?? "";
  useEffect(() => {
    if (!revisionOpen || !chosenVersionId) { setRevisionCandidates(null); return; }
    let cancelled = false;
    let timer: number | undefined;
    const controller = new AbortController();
    setRevisionCandidates({ kind: "loading" });
    async function refreshCandidates() {
      try {
        const next = await getV2RevisionCandidates(chosenVersionId, controller.signal);
        if (!cancelled) setRevisionCandidates({ kind: "ready", data: next });
      } catch (error) {
        if (!cancelled && !controller.signal.aborted) setRevisionCandidates({ kind: "error", message: errorMessage(error, "暂时无法读取可选修订材料。") });
      } finally {
        if (!cancelled) timer = window.setTimeout(() => { void refreshCandidates(); }, 10_000);
      }
    }
    void refreshCandidates();
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); controller.abort(); };
  }, [revisionOpen, chosenVersionId]);

  const revisionCandidatesData = revisionCandidates?.kind === "ready" && revisionCandidates.data.version_id === chosenVersionId ? revisionCandidates.data : null;
  const revisionSourceOptions = useMemo(() => (revisionCandidatesData?.candidates ?? []).map((candidate) => ({
    key: `${candidate.source_type}:${candidate.source_id}`,
    source_type: candidate.source_type,
    source_id: candidate.source_id,
    label: candidate.title,
    publishedAt: candidate.published_at,
    observedAt: candidate.observed_at,
    revisionType: candidate.category,
  })), [revisionCandidatesData]);
  const chosenSources = revisionSourceOptions.filter((source) => selectedSourceKeys.includes(source.key));

  // Arriving from a judgment's 用这份财报修订: open the existing revision form once the versions are known, and tick that
  // filing once the server lists it as a candidate.  If it is not a candidate the form just stays open, untouched.
  useEffect(() => {
    if (!reviseSourceId || reviseApplied.current || !versions.length) return;
    if (!revisionOpen) { setRevisionOpen(true); return; }
    const match = revisionSourceOptions.find((source) => source.source_type === "official_filing" && source.source_id.toLowerCase() === reviseSourceId);
    if (!match) return;
    reviseApplied.current = true;
    setSelectedSourceKeys([match.key]);
  }, [reviseSourceId, versions, revisionOpen, revisionSourceOptions]);

  async function createRevision() {
    if (!chosenVersion || !revisionCandidatesData || chosenSources.length === 0) return;
    setActionError(null);
    try {
      const job = await createV2ManualRevisionJob(chosenVersion.id, chosenSources.map((source) => ({ source_type: source.source_type, source_id: source.source_id })));
      setActiveJob(job);
      setRevisionOpen(false);
      setSelectedSourceKeys([]);
    } catch (error) {
      setActionError(errorMessage(error, "无法创建手动修订任务。"));
    }
  }

  function selectVersion(id: string) {
    setSelectedVersionId(id);
    // Keeps the address shareable without a navigation of its own.
    try { window.history.replaceState(window.history.state, "", hashHref(paths.forecast(rootId, { version: id }))); } catch { /* the page still works without it */ }
  }

  if (notFound) {
    return <section className="v2-desk v2-desk-forecast" aria-labelledby="forecast-page-title">
      <header className="v2-desk-heading"><div><h2 id="forecast-page-title">{t("找不到这项预测")}</h2><p>{t("这个地址指向的预测不存在，或已被移除。不会用其他预测代替它。")}</p></div></header>
      <button className="secondary-action" type="button" onClick={onHome}>{t("回到预测首页")}</button>
    </section>;
  }

  const latest = versions.at(-1) ?? null;
  const targetEndDate = timeline.kind === "ready" && typeof timeline.data.target_contract.target_end_date === "string" ? timeline.data.target_contract.target_end_date : null;
  const root: V2ForecastRoot | null = latest ? {
    id: rootId,
    decision_at: versions[0].decision_at,
    target_end_date: targetEndDate ?? "",
    model_status: latest.model_status,
    latest_version_id: latest.id,
    latest_version_no: latest.version_no,
    expired: expiredFromTarget(targetEndDate),
  } : null;
  const roots: ResourceState<V2ForecastRoots> = timeline.kind === "ready"
    ? { kind: "ready", data: { symbol: timeline.data.symbol, roots: root ? [root] : [] } }
    : timeline.kind === "error" ? { kind: "error", message: timeline.message } : { kind: "loading" };
  const selectedDetail = details?.kind === "ready" && details.data.current.id === selectedVersionId ? details.data.current : null;
  const rootIsRevisable = root?.expired === false;
  const revisionDisabledReason = root?.expired === true ? t("该预测的目标已到期，只能查看历史版本。") : root && root.expired === null ? t("该预测的目标合同无效，只能查看历史版本。") : null;
  const canCreateRevision = Boolean(chosenVersion && revisionCandidatesData && !revisionCandidatesData.expired && chosenSources.length > 0 && chosenSources.length <= 10 && !isActiveJob(activeJob));

  return <section className="v2-desk v2-desk-forecast" aria-labelledby="forecast-page-title">
    <header className="v2-desk-heading">
      <div>
        <p className="eyebrow">{t("单项预测")}{symbol ? ` · ${symbol}` : ""}</p>
        <h2 id="forecast-page-title">{symbol ? `${symbol} · ${t("预测")}` : t("预测")}</h2>
        <p>{t("概率未经校准，属实验性信息。仅供参考，买不买由你决定。")}</p>
      </div>
      <button className="secondary-action" type="button" onClick={onHome}>{t("回到预测首页")}</button>
    </header>

    {timeline.kind === "loading" && <p className="v2-root-loading">{<Tx text={"正在读取此预测链的版本结果…"} />}</p>}
    {timeline.kind === "error" && !notFound && <p className="v2-notice error" role="alert">{timeline.message}</p>}
    {activeJob && <JobStatus job={activeJob} />}
    {actionError && <p className="v2-notice error" role="alert">{actionError}</p>}

    {timeline.kind === "ready" && <>
      {selectedDetail && <ForecastVersionHeader version={selectedDetail} />}
      <ForecastSummary root={root} roots={roots} detail={details} />
      <ForecastPriceContextChart symbol={timeline.data.symbol} history={priceHistory} detail={details} showHistoricalOnly={false} />
      {details?.kind === "ready" && details.data.current.research_brief && <ResearchBriefView
        brief={details.data.current.research_brief}
        versionId={details.data.current.id}
        probabilities={hasDecisionProbabilities(details.data.current.model_status) ? details.data.current.decision_probabilities ?? null : null}
        modelStatus={details.data.current.model_status}
        modelManifest={details.data.current.model_manifest}
        evidenceManifest={details.data.current.evidence_version_manifest}
        onOpenAnalysis={(material) => navigate(materialAnalysisPath(material))}
      />}
      <div id="forecast-versions">
        <RevisionComparison timeline={timeline} detail={details} />
        <EvidenceEvents timeline={timeline} detail={details} selectedVersionId={selectedVersionId} onSelect={selectVersion} showSourceDetail={false} />
      </div>
      <ForecastRevisionForm
        versions={versions}
        rootIsRevisable={rootIsRevisable}
        jobActive={isActiveJob(activeJob)}
        revisionOpen={revisionOpen}
        setRevisionOpen={setRevisionOpen}
        revisionDisabledReason={revisionDisabledReason}
        parentVersionId={parentVersionId}
        setParentVersionId={setParentVersionId}
        selectedSourceKeys={selectedSourceKeys}
        setSelectedSourceKeys={setSelectedSourceKeys}
        revisionCandidates={revisionCandidates}
        revisionCandidatesData={revisionCandidatesData}
        revisionSourceOptions={revisionSourceOptions}
        canCreateRevision={canCreateRevision}
        onCreate={createRevision}
      />
      <EvaluationReadout evaluations={evaluations} selectedRootId={rootId} selectedVersionId={selectedVersionId} selectedVersionDetail={selectedDetail} />
      <ForecastAudit detail={details} />
    </>}
  </section>;
}
