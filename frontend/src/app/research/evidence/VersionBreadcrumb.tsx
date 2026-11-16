import { ChevronRight } from "lucide-react";
import type { V2ForecastRoots, V2Timeline } from "../../../types";
import { forecastCopy } from "../../../forecast-model.mjs";
import { useLocale } from "../../../i18n";
import { CrumbPicker, type Crumb } from "./CrumbPicker";

type Root = V2ForecastRoots["roots"][number];
type Version = V2Timeline["versions"][number];

const MODEL_PHRASE: Record<string, string> = { experimental_llm: "推理模型", research_only: "研究简报", experimental_joint: "联合研究" };
/** What kind of version it is, in the words the old picker used (an early-version record keeps the name the forecast copy gives it). */
const modelPhrase = (status: string) => status === "experimental_jev" ? forecastCopy({ model_status: status }).briefKickerModel : MODEL_PHRASE[status] ?? "行情基线";

/** 「MM-DD」 of a saved time in UTC (the zone every version time is stored in); an unreadable one is shown as it is. */
export function shortDay(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value.slice(0, 10) : date.toISOString().slice(5, 10);
}

/**
 * 面包屑式的版本选择 (design 4.7): 公司 › 预测 MM-DD › 第 N 版.  Each level is a combobox: the company picks among the watchlist (the address becomes that
 * company's evidence), the forecast among the company's forecasts (its newest version), the version among that forecast's versions.  Before the forecasts
 * and the versions are read, their levels show a dash; a company with no forecast has only the first level.
 */
export function VersionBreadcrumb({ symbol, companies, roots, rootId, versions, versionId, onCompany, onRoot, onVersion }: {
  symbol: string;
  companies: string[];
  roots: Root[] | null;
  rootId: string | null;
  versions: Version[] | null;
  versionId: string | null;
  onCompany: (symbol: string) => void;
  onRoot: (root: Root) => void;
  onVersion: (versionId: string) => void;
}) {
  const { t } = useLocale();
  const root = roots?.find(item => item.id === rootId) ?? null;
  const version = versions?.find(item => item.id === versionId) ?? null;
  const companyOptions: Crumb[] = [...new Set([...companies, symbol])].map(code => ({ id: code, label: code }));
  const rootOptions: Crumb[] = (roots ?? []).map(item => ({ id: item.id, label: `${t("预测")} ${shortDay(item.decision_at)}`, hint: `${t("最新第")} ${item.latest_version_no} ${t("版")}` }));
  const versionOptions: Crumb[] = [...(versions ?? [])].reverse().map(item => ({ id: item.id, label: `${t("第")} ${item.version_no} ${t("版")}`, hint: `${shortDay(item.decision_at)} · ${t(modelPhrase(item.model_status))}` }));
  const sep = <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />;
  return <nav data-testid="version-breadcrumb" aria-label={t("选择要查看的预测版本")} className="flex min-w-0 flex-wrap items-center gap-x-0.5 gap-y-1">
    <CrumbPicker level={t("公司")} current={symbol} options={companyOptions} selectedId={symbol} onPick={onCompany} testid="crumb-company" mono />
    {root && <>{sep}<CrumbPicker level={t("预测任务")} current={`${t("预测")} ${shortDay(root.decision_at)}`} options={rootOptions} selectedId={root.id} onPick={id => { const next = roots?.find(item => item.id === id); if (next) onRoot(next); }} testid="crumb-root" /></>}
    {root && version && <>{sep}<CrumbPicker level={t("预测版本")} current={`${t("第")} ${version.version_no} ${t("版")}`} options={versionOptions} selectedId={version.id} onPick={onVersion} testid="crumb-version" /></>}
  </nav>;
}
