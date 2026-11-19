import { useEffect, useMemo, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonCard } from "@/components/state/Skeleton";
import { getV2ForecastRoots, getV2ForecastVersion, getV2Timeline } from "../../../api/forecast-v2";
import type { ResearchMaterialReference } from "../../../types";
import { formatDateTime, getLocalePreference, useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { useAiContentLocalization, withLocalizedFields } from "../../../useAiContentLocalization";
import { useRead } from "../use-read";
import { actionMessage, isSupportedSymbol } from "../support";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { MaterialCard } from "./MaterialCard";
import { UploadDialog } from "./UploadDialog";
import { VersionBreadcrumb } from "./VersionBreadcrumb";
import { latestVersionId } from "./evidence-model.mjs";

export type EvidenceAddress = { versionId: string | null; sourceType: ResearchMaterialReference["source_type"] | null; sourceId: string | null };

function time(value: string | null | undefined) {
  if (!value) return getLocalePreference() === "en-US" ? "Time not recorded" : "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(date, getLocalePreference(), "UTC");
}

/**
 * 证据页 (#/research/evidence[/:versionId[/:sourceType/:sourceId]], design 4.7).  The title row is the version picker (company › forecast › version).  The body is
 * the grid of the materials the version's brief rests on (fact material); one opens in the drawer, and its address says so.  The address with no version opens the
 * company's newest forecast at its newest version, where it stands (it does not rewrite itself).  A company with no forecast still has the upload.
 */
export function EvidencePage({ symbol, companies, address, uploadOpen }: { symbol: string; companies: string[]; address: EvidenceAddress; uploadOpen: boolean }) {
  const { locale, t } = useLocale();
  const navigate = useNavigate();
  const location = useLocation();
  const routeVersionId = address.versionId;
  const opened = useRef<string | null>(null);

  // The version in the address says whose evidence this is; with no version, the company is the one the page was given.
  const [byRoute, retryRoute] = useRead(`ev-version:${routeVersionId}`, signal => getV2ForecastVersion(routeVersionId!, signal), Boolean(routeVersionId));
  const rootsSymbol = routeVersionId && byRoute.kind === "ready" ? byRoute.value.symbol : symbol;
  const [roots, retryRoots] = useRead(`ev-roots:${rootsSymbol}`, signal => getV2ForecastRoots(rootsSymbol, signal), !routeVersionId || byRoute.kind !== "loading");
  const indexVersionId = !routeVersionId && roots.kind === "ready" ? latestVersionId(roots.value.roots) : null;
  const [byIndex, retryIndex] = useRead(`ev-version:${indexVersionId}`, signal => getV2ForecastVersion(indexVersionId!, signal), Boolean(indexVersionId));
  const version = routeVersionId ? byRoute : byIndex;
  const versionData = version.kind === "ready" ? version.value : null;
  const pageSymbol = versionData?.symbol ?? symbol;
  const rootId = versionData?.root_id ?? (!routeVersionId && roots.kind === "ready" ? roots.value.roots[0]?.id ?? null : null);
  const [timeline] = useRead(`ev-timeline:${rootId}`, signal => getV2Timeline(rootId!, signal), Boolean(rootId));

  const localization = useAiContentLocalization("forecast_brief", versionData?.id);
  const sourceBrief = versionData?.research_brief ?? null;
  const brief = sourceBrief && localization.kind === "ready" ? withLocalizedFields(sourceBrief, localization.fields) : sourceBrief;
  const refs = brief?.material_refs ?? [];
  const versionId = versionData?.id ?? routeVersionId ?? indexVersionId;

  const versionHref = versionId ? paths.evidence(versionId) : paths.evidenceIndex({ symbol: pageSymbol });
  const baseHref = address.sourceId && address.sourceType && versionId ? paths.evidence(versionId, address.sourceType, address.sourceId) : versionId && routeVersionId ? versionHref : paths.evidenceIndex({ symbol: pageSymbol });
  const uploadHref = baseHref.includes("?") ? `${baseHref}&upload=1` : `${baseHref}?upload=1`;

  const source = useMemo(() => address.sourceId ? refs.find(item => item.source_type === address.sourceType && item.source_id === address.sourceId) ?? null : null, [refs, address.sourceType, address.sourceId]);
  useEffect(() => { if (address.sourceId) opened.current = address.sourceId; }, [address.sourceId]);

  const failedVersion = version.kind === "error" ? actionMessage(version.error, "暂时无法读取该预测版本的证据。") : null;
  const drawerBody = !address.sourceId ? ({ kind: "loading" } as const)
    : failedVersion ? ({ kind: "error", message: failedVersion } as const)
    : !versionData ? ({ kind: "loading" } as const)
    : source ? ({ kind: "ready", version: versionData, brief, source } as const) : ({ kind: "missing" } as const);

  const closeDrawer = () => { if ((location.state as { fromGrid?: boolean } | null)?.fromGrid) navigate(-1); else navigate(versionHref, { replace: true }); };
  const openCard = (item: ResearchMaterialReference) => { if (versionData) navigate(paths.evidence(versionData.id, item.source_type, item.source_id), { state: { fromGrid: true } }); };
  const returnFocus = () => { const id = opened.current; if (id) document.querySelector<HTMLElement>(`[data-testid=evidence-card][data-source-id="${CSS.escape(id)}"] [data-testid=card-open]`)?.focus(); };
  const closeUpload = () => navigate(baseHref, { replace: true });

  const rootList = roots.kind === "ready" ? roots.value.roots : null;
  const noForecast = rootList !== null && rootList.length === 0 && !routeVersionId;
  const loading = !noForecast && roots.kind !== "error" && !failedVersion && (version.kind === "loading" || (!routeVersionId && roots.kind === "loading"));
  const roster = (
    <ul data-testid="evidence-grid" aria-label={versionData ? `${pageSymbol} ${t("第")} ${versionData.version_no} ${t("版引用材料")}` : undefined} className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 xl:grid-cols-3">
      {refs.map((item, index) => <MaterialCard key={`${item.source_type}:${item.source_id}:${item.analysis_id}`} ordinal={index + 1} source={item} brief={brief!} active={item.source_type === address.sourceType && item.source_id === address.sourceId} onOpen={() => openCard(item)} />)}
    </ul>);

  return <main data-testid="evidence-page" aria-labelledby="evidence-title" className="mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6">
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 id="evidence-title" className="sr-only">{t("证据")}</h1>
      <VersionBreadcrumb symbol={pageSymbol} companies={companies} roots={rootList} rootId={rootId} versions={timeline.kind === "ready" ? timeline.value.versions : null} versionId={versionData?.id ?? null}
        onCompany={code => navigate(paths.evidenceIndex({ symbol: code }))} onRoot={root => navigate(paths.evidence(root.latest_version_id))} onVersion={id => navigate(paths.evidence(id))} />
      {versionData && <span data-testid="evidence-decision" className="text-caption text-muted-foreground">{t("决策时间")} {time(versionData.decision_at)}</span>}
      <Button asChild className="ml-auto"><Link to={uploadHref} data-testid="open-upload" aria-haspopup="dialog"><Upload aria-hidden="true" />{t("上传媒体材料")}</Link></Button>
    </header>
    <p className="max-w-3xl text-small text-muted-foreground mb-[1em]">{t("按预测版本查看简报实际引用的材料及其事件判断。候选冻结材料只有被简报引用后才会出现在这里。")}</p>

    {roots.kind === "error" && !routeVersionId && <ErrorBar message={actionMessage(roots.error, "暂时无法读取预测版本。")} onRetry={retryRoots} />}
    {failedVersion && <ErrorBar message={failedVersion} onRetry={routeVersionId ? retryRoute : retryIndex} />}
    {localization.kind === "loading" && <p role="status" className="text-caption text-muted-foreground mb-[1em]">{t("Translating saved research brief…")}</p>}
    {localization.kind === "error" && <p role="status" className="text-caption text-muted-foreground mb-[1em]">{t("English translation is temporarily unavailable; showing the saved original.")}</p>}

    {loading && <DelayedSkeleton><div data-testid="evidence-loading" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div></DelayedSkeleton>}
    {noForecast && <EmptyState title={t("创建预测后，这里会整理实际引用的材料")} description={t("SEC 原始材料和 AI 分析历史仍在材料库中管理。媒体材料可以先上传保存，分析后再由预测版本引用。")} action={{ label: t("前往预测工作台"), to: paths.forecasts() }} className="rounded-md border border-dashed border-line" />}
    {versionData && !brief && <EmptyState title={t("这个版本没有可展示的材料事件")} description={t("版本记录和冻结候选材料可以在预测工作台查看。")} action={{ label: t("去预测页看冻结候选"), to: paths.forecast(versionData.root_id, { version: versionData.id, section: "audit" }) }} className="rounded-md border border-dashed border-line" />}
    {versionData && brief && refs.length === 0 && <EmptyState title={t("该版本没有引用已分析材料")} description={t("只有进入研究简报的材料才会出现在这里。")} action={{ label: t("去预测页看冻结候选"), to: paths.forecast(versionData.root_id, { version: versionData.id, section: "audit" }) }} className="rounded-md border border-dashed border-line" />}
    {versionData && brief && refs.length > 0 && roster}

    <EvidenceDrawer open={Boolean(address.sourceId)} body={drawerBody} versionHref={versionHref} onClose={closeDrawer} returnFocus={returnFocus} />
    {uploadOpen && <UploadDialog symbol={pageSymbol} supported={isSupportedSymbol(pageSymbol)} onClose={closeUpload} returnFocus={() => document.querySelector<HTMLElement>("[data-testid=open-upload]")?.focus()} />}
  </main>;
}
