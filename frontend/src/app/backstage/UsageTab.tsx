import { useState } from "react";
import { Link } from "react-router";
import { Segmented } from "@/components/Segmented";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { EmptyState } from "@/components/state/EmptyState";
import { readUsage, type Usage } from "../../api/backstage";
import { USAGE_GROUPS, USAGE_PRESETS, usageRange, usageRow, usageTotalsRow, type UsageRow } from "../../backstage-view.mjs";
import { colon, useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { useLoad } from "../use-load";
import { BackstageTable, CostText, type Column } from "./BackstageTable";
import { useWords } from "./words";

type Preset = "7" | "30" | "custom";
const dateField = "h-9 rounded-sm border border-input bg-background px-2 font-mono text-small text-ink outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 max-sm:h-11";

/**
 * 用量: what the models were asked and what it came to, for a range of days (UTC days, said on the page) grouped by day, model, bot or purpose.  A table with a totals line;
 * a call to a model with no price shows its tokens and 「未设价格」 (with which price is missing and the way to settings → models), never an invented cost.  No chart: the table is the whole of it.
 */
export function UsageTab() {
  const { t } = useLocale();
  const w = useWords();
  const today = new Date().toISOString().slice(0, 10);     // read on every draw: a page left open past UTC midnight moves its end date with the clock
  const [preset, setPreset] = useState<Preset>("7");
  const [custom, setCustom] = useState(() => usageRange(7, today));
  const [group, setGroup] = useState("day");
  const range = preset === "custom" ? custom : usageRange(Number(preset), today);
  const valid = Boolean(range.from) && Boolean(range.to) && range.from <= range.to;
  const load = useLoad<Usage | null>(signal => (valid ? readUsage({ ...range, group }, signal) : Promise.resolve(null)), `${range.from}|${range.to}|${group}|${valid}`);
  // Numbers are shown only for the request they answer: while another range or grouping loads (or fails), the previous ones are not left under the new dates.
  const data = load.data && load.data.group === group && load.data.from === range.from && load.data.to === range.to ? load.data : null;
  const rows = data ? data.groups.map(row => usageRow(row, data.group, w)) : [];
  const totals = data ? usageTotalsRow(data.totals, w) : null;
  const header = USAGE_GROUPS.find(option => option.value === group)?.label ?? "按天";
  const firstHeader = { day: t("日期（UTC）"), model: t("模型"), bot: "bot", purpose: t("用途") }[group] ?? t("日期");

  const columns: Column<UsageRow>[] = [
    { key: "label", header: firstHeader, wide: true, cell: row => <span className={row.key === "total" ? "font-medium text-ink" : "text-ink"}>{row.label}</span> },
    { key: "calls", header: t("调用"), cell: row => <span className="font-mono tabular-nums">{row.calls}</span> },
    { key: "failed", header: t("失败"), cell: row => <span className="font-mono tabular-nums">{row.failed}</span> },
    { key: "input", header: t("输入 token"), cell: row => <span className="font-mono tabular-nums">{row.input}</span> },
    { key: "output", header: t("输出 token"), cell: row => <span className="font-mono tabular-nums">{row.output}</span> },
    { key: "cache", header: t("缓存读 / 写"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.cache}</span> },
    { key: "p50", header: t("耗时中位"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.p50}</span> },
    { key: "cost", header: t("费用"), cell: row => <span className="flex flex-col items-start gap-0.5">
      <CostText cost={row.cost} />
      {row.unpriced_calls > 0 && row.cost.kind === "amount" && <span className="text-caption text-muted-foreground">{t("另有 {n} 次调用未设价格").replace("{n}", String(row.unpriced_calls))}</span>}
    </span> },
    { key: "missing", header: t("缺的价格"), wide: true, cell: row => row.missing.length ? <span className="text-caption text-ink-2">{row.missing.join(w.list)}</span> : <span className="text-muted-foreground">—</span> },
  ];
  const unpriced = data?.totals.unpriced_calls ?? 0;

  return <div data-testid="usage-tab" className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
      <Segmented name="usage-range" testid="usage-range" legend={t("时间范围")} value={preset} onChange={setPreset} options={[
        ...USAGE_PRESETS.map(days => ({ value: String(days) as Preset, label: `${t("最近")} ${days} ${t("天")}` })), { value: "custom" as Preset, label: t("自定义") }]} />
      <Segmented name="usage-group" testid="usage-group" legend={t("分组")} value={group} onChange={setGroup} options={USAGE_GROUPS.map(option => ({ value: option.value, label: t(option.label) }))} />
      {preset === "custom" && <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-caption text-muted-foreground">{t("从")}
          <input type="date" data-testid="usage-from" value={custom.from} max={custom.to || undefined} onChange={event => setCustom(current => ({ ...current, from: event.target.value }))} className={dateField} /></label>
        <label className="flex flex-col gap-1 text-caption text-muted-foreground">{t("到")}
          <input type="date" data-testid="usage-to" value={custom.to} min={custom.from || undefined} onChange={event => setCustom(current => ({ ...current, to: event.target.value }))} className={dateField} /></label>
      </div>}
    </div>
    <p data-testid="usage-timezone" className="text-caption text-muted-foreground">{`${t("日期按 UTC 日计算（00:00 到 24:00 UTC）")}${colon()}${range.from} → ${range.to}`}</p>
    {!valid && <p role="alert" className="text-small text-danger">{t("起始日期要不晚于结束日期。")}</p>}
    {load.error && !load.loading ? <ErrorBar error={load.error} onRetry={() => void load.reload()} retrying={load.loading} /> : null}
    {load.loading && !data && valid ? <DelayedSkeleton><div data-testid="backstage-loading"><SkeletonRows rows={5} /></div></DelayedSkeleton> : null}
    {data && unpriced > 0 && <div data-testid="unpriced-note" role="note" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2">
      <span><span className="font-medium text-ink">{t("未设价格")}</span>{colon()}{t("{n} 次调用用了没有填价格的模型，只显示 token，不算花费。").replace("{n}", String(unpriced))}</span>
      {totals && totals.missing.length > 0 && <span className="text-caption">{`${t("缺的价格")}${colon()}${totals.missing.join(w.list)}`}</span>}
      <Link to={paths.settings("models")} data-testid="unpriced-settings" className="text-action underline-offset-2 hover:underline">{t("去设置 → 模型 填价格")}</Link>
    </div>}
    {data && rows.length === 0 && <div data-testid="backstage-empty"><EmptyState title={t("这段时间没有模型调用的记录。")} description={t("换一个时间范围，或者等助手回答几次。")} /></div>}
    {data && rows.length > 0 && totals && <BackstageTable testId="usage-table" label={`${t("用量")} ${t(header)}`} columns={columns} rows={[...rows, totals]} rowKey={row => row.key}
      rowClass={row => (row.key === "total" ? "bg-sunken font-medium" : undefined)} />}
  </div>;
}
