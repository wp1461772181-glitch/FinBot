import { ProbabilityBar } from "@/components/ProbabilityBar";
import { cn } from "@/lib/utils";
import type { V2Timeline, V2VersionDetail } from "../../../types";
import { hasDecisionProbabilities, recordedModel } from "../../../forecast-model.mjs";
import { sourceDiff } from "../../../forecast-detail.mjs";
import { useLocale } from "../../../i18n";

const marketSummary = (manifest: Record<string, unknown>) => [manifest.price_input_sha256, manifest.market_cutoff_at, manifest.latest_completed_session].map(String).join("|");

function probabilitiesOf(version: V2VersionDetail) {
  return hasDecisionProbabilities(version.model_status) ? version.decision_probabilities : version.model_status === "experimental_joint" ? version.joint_probabilities : null;
}

/** The change in whole percentage points, signed ("+3"); "—" when a side has no probabilities. */
function points(now: number | undefined, before: number | undefined) {
  if (now === undefined || before === undefined) return "—";
  const value = Math.round(now * 100) - Math.round(before * 100);
  return `${value > 0 ? "+" : ""}${value}`;
}

/**
 * 版本对比 (the old 修订对比): how many versions the chain has, the fixed target, and the selected version set beside its parent: the model, the three
 * probabilities and their change, the market cut-off and what the sources did (added, replaced, removed, inherited).  A first version has no parent to
 * compare with and says so.  The market inputs sentence and the note that no attribution has been verified are the old ones.
 */
export function VersionsPanel({ timeline, current, parent }: { timeline: V2Timeline; current: V2VersionDetail | undefined; parent: V2VersionDetail | undefined }) {
  const { t, locale } = useLocale();
  const versions = timeline.versions;
  const diff = current ? sourceDiff(current, parent ?? null) : null;
  const marketChanged = current && parent ? marketSummary(current.price_input_manifest) !== marketSummary(parent.price_input_manifest) : false;
  const nowP = current ? probabilitiesOf(current) : null;
  const beforeP = parent ? probabilitiesOf(parent) : null;
  const count = locale === "en-US" ? `${versions.length} historical ${versions.length === 1 ? "version" : "versions"}` : `${versions.length} ${t("个历史版本")}`;
  const target = String(timeline.target_contract.target_end_date ?? t("已记录"));
  const head = "whitespace-nowrap px-3 py-2 text-left text-caption font-normal text-muted-foreground";
  const cell = "px-3 py-2 align-top text-small text-ink";
  const rowOf = (label: string, now: string, before: string, change?: string) => <tr key={label} className="border-t border-line"><th scope="row" className={cn(head, "text-ink-2")}>{label}</th><td className={cell}>{now}</td><td className={cn(cell, "text-ink-2")}>{before}</td><td className={cn(cell, "font-mono tabular-nums")}>{change ?? ""}</td></tr>;
  return <section data-testid="forecast-compare" aria-labelledby="compare-title" className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-col gap-1">
      <h3 id="compare-title" className="text-title-s text-ink">{versions.length ? count : t("尚无版本链")}</h3>
      <p className="text-small text-muted-foreground">{versions.length > 1 ? t("每个子版本保留固定目标合同；版本差异见「审计与来源」页签里的事件记录。") : t("出现新的合规材料后，可以用页面右上角的「发起修订」选择版本发起人工修订。")}</p>
    </div>
    {versions.length > 0 && <dl className="m-0 flex flex-wrap gap-x-8 gap-y-1 text-small">
      <div className="flex gap-2"><dt className="text-muted-foreground">{t("固定目标")}</dt><dd data-testid="compare-target" className="m-0 font-mono tabular-nums text-ink">{target}</dd></div>
      <div className="flex gap-2"><dt className="text-muted-foreground">{t("当前版本")}</dt><dd className="m-0 text-ink">{t("第")} {versions.at(-1)?.version_no} {t("版")}</dd></div>
    </dl>}
    {current && parent && <p className="text-small text-ink-2">{locale === "en-US" ? `${t("市场输入：")} ${marketChanged ? t("已更新（见下方截止时间）") : t("与父版清单一致")}. ${t("本系统尚未验证各输入对市场结果的定量归因。")}` : `${t("市场输入：")}${marketChanged ? t("已更新（见下方截止时间）") : t("与父版清单一致")}。${t("本系统尚未验证各输入对市场结果的定量归因。")}`}</p>}
    {current && !parent && <p className="text-small text-muted-foreground">{t("初始版本没有父版本可比较。")}</p>}
    {current && parent && <div className="min-w-0 overflow-x-auto rounded-md border border-line bg-surface">
      <table data-testid="compare-table" className="w-full min-w-[20rem] border-collapse">
        <caption className="sr-only">{t("所选版本与上一版的对比")}</caption>
        <thead><tr><th scope="col" className={head}><span className="sr-only">{t("项目")}</span></th><th scope="col" className={head}>{t("第")} {current.version_no} {t("版")}</th><th scope="col" className={head}>{t("第")} {parent.version_no} {t("版")}</th><th scope="col" className={head}>{t("变化")}</th></tr></thead>
        <tbody>
          {rowOf(t("决策模型"), recordedModel(current).actual_model ?? t("未记录"), recordedModel(parent).actual_model ?? t("未记录"))}
          {nowP && beforeP && (["bearish", "neutral", "bullish"] as const).map(key => rowOf(t(key === "bearish" ? "下跌" : key === "neutral" ? "持平" : "上涨"), `${Math.round(nowP[key] * 100)}%`, `${Math.round(beforeP[key] * 100)}%`, points(nowP[key], beforeP[key])))}
          {(!nowP || !beforeP) && <tr className="border-t border-line"><th scope="row" className={cn(head, "text-ink-2")}>{t("概率")}</th><td className={cell} colSpan={3}>{nowP ? <ProbabilityBar probabilities={nowP} size="mini" focusable={false} /> : t("该版本没有数值概率")}</td></tr>}
          {rowOf(t("行情截止"), current.market_cutoff_at.slice(0, 10), parent.market_cutoff_at.slice(0, 10))}
          {diff && <tr className="border-t border-line"><th scope="row" className={cn(head, "text-ink-2")}>{t("来源")}</th><td className={cell} colSpan={3}>{`${t("新增")} ${diff.added} · ${t("状态替换")} ${diff.replaced} · ${t("移除")} ${diff.removed} · ${t("继承")} ${diff.inherited}`}</td></tr>}
        </tbody>
      </table>
    </div>}
  </section>;
}
