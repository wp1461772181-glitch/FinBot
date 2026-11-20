import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { ArrowLeft, FilePen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DelayedSkeleton, SkeletonCard, SkeletonRows } from "@/components/state/Skeleton";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { useRunningTasks } from "@/components/state/tasks";
import { cn } from "@/lib/utils";
import { ApiError } from "../../../api/base";
import { getV2Evaluations, getV2Timeline } from "../../../api/forecast-v2";
import { getV2Prices } from "../../../api/prices";
import type { PriceHistory, V2EvaluationResponse, V2ForecastJob, V2Timeline } from "../../../types";
import { DETAIL_SECTIONS, SECTION_PHRASE, detailSection, modelChangedIds, reviseGate } from "../../../forecast-detail.mjs";
import type { DetailSection } from "../../../forecast-detail.mjs";
import { modelChanged } from "../../../forecast-model.mjs";
import type { ResourceState } from "../../../ForecastShared";
import { useLocale } from "../../../i18n";
import { hashHref, paths } from "../../../routes.mjs";
import { actionMessage } from "../support";
import { AuditPanel } from "./AuditPanel";
import { BriefSection } from "./BriefSection";
import { EvaluationPanel } from "./EvaluationPanel";
import { JudgmentBlock } from "./JudgmentBlock";
import { PriceContext } from "./PriceContext";
import { ReviseDrawer } from "./ReviseDrawer";
import { TaskStrip } from "./TaskStrip";
import { VersionRail } from "./VersionRail";
import { VersionsPanel } from "./VersionsPanel";
import { JOB_TASK_PREFIX, followJob, onJobSettled } from "./jobs";
import { useVersionDetails } from "./useVersionDetails";

type Read<T> = { kind: "loading" } | { kind: "ready"; data: T } | { kind: "error"; message: string };

/**
 * 单项预测 (#/research/forecasts/:rootId, design 4.6): a main column (the judgment card, the chart, the research brief), the version rail beside it and three
 * tabs under it (版本对比, 到期评估, 审计与来源).  ?version= says which version, ?section= which tab, ?revise= opens the drawer on a library filing.  The
 * company comes from the forecast itself, never from a picker; a forecast that cannot be read is reported as that page and no other forecast stands in for it.
 * Picking a version or a tab rewrites the address in place (`replace`, as the page always did: the history keeps one entry for the page, not one per click).
 */
export function ForecastDetail({ rootId, versionId, reviseSourceId, section }: { rootId: string; versionId?: string; reviseSourceId?: string; section: string | null }) {
  const { t } = useLocale();
  const [timeline, setTimeline] = useState<Read<V2Timeline>>({ kind: "loading" });
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedId, setSelectedId] = useState(versionId ?? "");
  const [tab, setTab] = useState<DetailSection>(detailSection(section));
  const [inUrl, setInUrl] = useState<string | null>(section);
  const [evaluations, setEvaluations] = useState<ResourceState<V2EvaluationResponse>>({ kind: "loading" });
  const [priceHistory, setPriceHistory] = useState<PriceHistory | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pendingSelect, setPendingSelect] = useState<string | null>(null);
  const mine = useRef(new Set<string>());
  const deeplinked = useRef(false);
  const scrolled = useRef(false);
  const tabs = useRef<HTMLDivElement>(null);
  const reviseButton = useRef<HTMLButtonElement>(null);
  const jobRunning = useRunningTasks().some(task => task.id.startsWith(JOB_TASK_PREFIX));

  useEffect(() => { setSelectedId(versionId ?? ""); }, [rootId, versionId]);

  useEffect(() => {
    const controller = new AbortController();
    setNotFound(false);
    getV2Timeline(rootId, controller.signal)
      .then(next => { if (!controller.signal.aborted) setTimeline({ kind: "ready", data: next }); })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && (error.status === 404 || error.status === 422)) setNotFound(true);
        setTimeline({ kind: "error", message: actionMessage(error, "无法读取所选预测的版本链。") });
      });
    return () => controller.abort();
  }, [rootId, reloadKey]);

  const data = timeline.kind === "ready" ? timeline.data : null;
  const versions = useMemo(() => data?.versions ?? [], [data]);
  const symbol = data?.symbol ?? null;

  // The address may name no version, or one that is not in the chain: the newest is shown, as ever.
  useEffect(() => {
    if (versions.length && !versions.some(version => version.id === selectedId)) setSelectedId(versions.at(-1)!.id);
  }, [versions, selectedId]);

  const details = useVersionDetails(versions, selectedId, rootId);
  const selected = versions.find(version => version.id === selectedId) ?? null;
  const current = selected ? details.get(selected.id) : undefined;
  const parent = selected?.parent_version_id ? details.get(selected.parent_version_id) : undefined;
  const changedIds = modelChangedIds(versions, details.all, modelChanged);

  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    setEvaluations({ kind: "loading" });
    getV2Evaluations(symbol, controller.signal)
      .then(next => { if (!controller.signal.aborted) setEvaluations({ kind: "ready", data: next }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setEvaluations({ kind: "error", message: actionMessage(error, "暂时无法读取到期评估。") }); });
    getV2Prices(symbol, controller.signal)
      .then(next => { if (!controller.signal.aborted) setPriceHistory(next.price_history); })
      .catch(() => { if (!controller.signal.aborted) setPriceHistory(null); });
    return () => controller.abort();
  }, [symbol, reloadKey]);

  // A job of this company that ends changes the chain (or does not): the chain is read again; a revision this page started moves the page to the version it made.
  useEffect(() => onJobSettled((job: V2ForecastJob) => {
    if (!mine.current.has(job.id) && job.symbol !== symbol) return;
    setReloadKey(value => value + 1);
    if (mine.current.has(job.id) && job.result_version_id) setPendingSelect(job.result_version_id);
  }), [symbol]);

  const writeAddress = (version: string, nextSection: string | null) => {
    // Keeps the address shareable without a navigation of its own (the router is not asked, the page does not read itself again).
    try { window.history.replaceState(window.history.state, "", hashHref(paths.forecast(rootId, { version, section: nextSection ?? undefined }))); } catch { /* the page still works without it */ }
  };
  const selectVersion = (id: string) => { setSelectedId(id); writeAddress(id, inUrl); };
  useEffect(() => {
    if (pendingSelect && versions.some(version => version.id === pendingSelect)) { selectVersion(pendingSelect); setPendingSelect(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingSelect, versions]);
  const pickTab = (next: DetailSection) => { setTab(next); setInUrl(next); if (selected) writeAddress(selected.id, next); };

  const target = typeof data?.target_contract.target_end_date === "string" ? data.target_contract.target_end_date : null;
  const gate = reviseGate(target, new Date().toISOString().slice(0, 10));
  const canRevise = versions.length > 0 && gate.allowed && !jobRunning;

  // An address with ?revise= opens the drawer once the chain is known (when the forecast can be revised at all); the drawer finds the filing, it does not tick it.
  useEffect(() => {
    if (!reviseSourceId || deeplinked.current || !versions.length || !gate.allowed) return;
    deeplinked.current = true;
    setDrawerOpen(true);
  }, [reviseSourceId, versions.length, gate.allowed]);
  // The old #revisions address lands on the tabs: an address that names a tab brings it into view once.
  useEffect(() => {
    if (section && !scrolled.current && data) { scrolled.current = true; tabs.current?.scrollIntoView?.(); }
  }, [section, data]);

  const onSubmitted = (job: V2ForecastJob) => {
    mine.current.add(job.id);
    followJob(job, `${t("修订预测")} · ${job.symbol}`);
  };
  const moveTab = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const buttons = [...(tabs.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [])];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0 || (!step && event.key !== "Home" && event.key !== "End")) return;
    event.preventDefault();
    buttons[event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (at + step + buttons.length) % buttons.length]?.focus();
  };

  if (notFound) {
    return <main data-testid="forecast-missing" className="mx-auto flex w-full max-w-[1280px] flex-1 flex-col p-4 lg:p-6">
      <EmptyState title={t("找不到这项预测")} description={t("这个地址指向的预测不存在，或已被移除。不会用其他预测代替它。")} action={{ label: t("回到预测首页"), to: paths.forecasts() }} />
    </main>;
  }
  const compareReady = Boolean(current) && (!current?.parent_version_id || Boolean(parent));
  const tabLabel = (id: DetailSection) => t(SECTION_PHRASE[id]);
  return <main data-testid="forecast-page" data-root={rootId} aria-labelledby="forecast-title" className="mx-auto flex w-full max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6">
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Link to={paths.forecasts()} data-testid="forecast-back" className="inline-flex h-8 items-center gap-1 rounded-sm text-small text-ink-2 outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11 underline"><ArrowLeft aria-hidden="true" className="size-4" />{t("预测")}</Link>
      <h1 id="forecast-title" className="min-w-0 text-title-m text-ink mb-3.5"><span className="font-mono">{symbol ?? "…"}</span> · {t("预测")}</h1>
      <div className="ml-auto flex flex-col items-end gap-1">
        <Button ref={reviseButton} type="button" data-testid="revise-open" disabled={!canRevise} aria-describedby={!gate.allowed ? "revise-reason" : undefined} onClick={() => setDrawerOpen(true)}><FilePen aria-hidden="true" />{t("发起修订")}</Button>
        {timeline.kind === "ready" && !gate.allowed && <p id="revise-reason" data-testid="revise-reason" role="status" className="max-w-xs text-right text-caption text-muted-foreground">{t(gate.reason!)}</p>}
        {timeline.kind === "ready" && gate.allowed && jobRunning && <p data-testid="revise-reason" role="status" className="text-caption text-muted-foreground">{t("任务处理中…")}</p>}
      </div>
    </header>
    <TaskStrip />
    {timeline.kind === "error" && <ErrorBar message={timeline.message} onRetry={() => { setTimeline({ kind: "loading" }); setReloadKey(value => value + 1); }} />}
    {timeline.kind === "loading" && <DelayedSkeleton><div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]"><div className="flex flex-col gap-4"><SkeletonCard /><SkeletonCard /></div><SkeletonRows rows={4} /></div></DelayedSkeleton>}

    {data && selected && <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="flex min-w-0 flex-col gap-4">
        {current
          ? <>
            <JudgmentBlock version={current} />
            <PriceContext symbol={data.symbol} history={priceHistory} version={current} />
            {current.research_brief && <BriefSection version={current} brief={current.research_brief} />}
          </>
          : details.failed
            ? <ErrorBar message={t("无法读取冻结版本详情。")} onRetry={details.retry} />
            : <DelayedSkeleton><SkeletonCard /><SkeletonCard /></DelayedSkeleton>}

        <section data-testid="forecast-tabs" aria-label={t("版本与来源")} className="flex min-w-0 flex-col gap-4">
          <div ref={tabs} role="tablist" aria-label={t("版本与来源")} onKeyDown={moveTab} className="flex gap-1 overflow-x-auto border-b border-line">
            {DETAIL_SECTIONS.map(id => <button key={id} type="button" role="tab" id={`forecast-tab-${id}`} data-testid={`tab-${id}`} aria-selected={tab === id} aria-controls="forecast-tab-panel" tabIndex={tab === id ? 0 : -1} onClick={() => pickTab(id)}
              className={cn("-mb-px min-h-11 whitespace-nowrap border-x-0 border-t-0 border-b-2 bg-transparent px-4 text-body outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring lg:min-h-10 cursor-pointer appearance-auto py-px", tab === id ? "border-brand font-medium text-ink" : "border-transparent text-muted-foreground hover:text-ink")}>{tabLabel(id)}</button>)}
          </div>
          <div role="tabpanel" id="forecast-tab-panel" aria-labelledby={`forecast-tab-${tab}`} tabIndex={-1} className="min-w-0 outline-none">
            {tab === "versions" && (compareReady ? <VersionsPanel timeline={data} current={current} parent={parent} /> : <SkeletonCard />)}
            {tab === "evaluation" && <EvaluationPanel evaluations={evaluations} selectedRootId={rootId} selectedVersionId={selected.id} selectedVersionDetail={current ?? null} />}
            {tab === "audit" && (compareReady ? <AuditPanel timeline={data} current={current} parent={parent} selectedId={selected.id} onSelect={selectVersion} /> : <SkeletonCard />)}
          </div>
        </section>
      </div>
      <VersionRail versions={versions} selectedId={selected.id} onSelect={selectVersion} details={details} changedIds={changedIds} />
    </div>}

    {data && <ReviseDrawer open={drawerOpen} onOpenChange={setDrawerOpen} versions={versions} locate={reviseSourceId} onSubmitted={onSubmitted} jobActive={jobRunning} returnFocus={() => reviseButton.current?.focus()} />}
  </main>;
}
