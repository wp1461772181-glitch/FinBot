import { X } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLocale } from "../../../i18n";
import { ORDER_PHRASE, SOURCE_PHRASE, STATUSES, STATUS_PHRASE, activeFilters, type FilterKey, type Filters } from "./materials-model.mjs";

/**
 * 筛选条 (design 4.7): company, source, analysis status, order, as four selects with the old values; what differs from the default shows under them as
 * chips, each of which takes its filter off.  The count of the list stands at the end.
 */
export function MaterialFilters({ symbol, filters, total, onChange, onClear }: { symbol: string; filters: Filters; total: number | null; onChange: (key: FilterKey, value: string) => void; onClear: (key: FilterKey) => void }) {
  const { t } = useLocale();
  const chips = activeFilters(filters);
  const control = (key: FilterKey, label: string, value: string, items: Array<[string, string]>) => <div className="flex min-w-0 flex-col gap-1">
    <span id={`filter-label-${key}`} className="text-caption text-muted-foreground">{label}</span>
    <Select value={value} onValueChange={next => onChange(key, next)}>
      <SelectTrigger size="sm" data-testid={`filter-${key}`} aria-labelledby={`filter-label-${key}`} className="min-w-32 max-sm:h-11 max-sm:w-full"><SelectValue /></SelectTrigger>
      <SelectContent position="popper">{items.map(([id, phrase]) => <SelectItem key={id} value={id} data-filter-option={id}>{phrase}</SelectItem>)}</SelectContent>
    </Select>
  </div>;
  return <div data-testid="material-filters" className="flex min-w-0 flex-col gap-2">
    <div className="grid min-w-0 grid-cols-2 gap-x-3 gap-y-2 sm:flex sm:flex-wrap sm:items-end">
      {control("scope", t("公司"), filters.scope, [["current", `${t("当前股票")} · ${symbol}`], ["all", t("全部股票")]])}
      {control("sourceType", t("来源"), filters.sourceType, [["all", t("全部来源")], ...Object.entries(SOURCE_PHRASE).map(([id, phrase]) => [id, t(phrase)] as [string, string])])}
      {control("analysisStatus", t("分析状态"), filters.analysisStatus, [["all", t("全部状态")], ...STATUSES.map(id => [id, t(STATUS_PHRASE[id])] as [string, string])])}
      {control("order", t("排序"), filters.order, Object.entries(ORDER_PHRASE).map(([id, phrase]) => [id, t(phrase)] as [string, string]))}
      <span data-testid="material-count" className="ml-auto self-end pb-1.5 font-mono text-caption text-muted-foreground max-sm:col-span-2 max-sm:ml-0">{total === null ? "" : `${total} ${t("份材料")}`}</span>
    </div>
    {chips.length > 0 && <ul data-testid="filter-chips" aria-label={t("已选筛选")} className="m-0 flex list-none flex-wrap gap-1.5 p-0">
      {chips.map(chip => <li key={chip.key}><button type="button" data-testid="filter-chip" data-filter={chip.key} aria-label={`${t("清除筛选")}：${t(chip.phrase)}`} onClick={() => onClear(chip.key)}
        className="inline-flex h-8 items-center gap-1 rounded-sm border border-line-strong bg-sunken px-2 text-small text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11 cursor-pointer appearance-auto py-px">{t(chip.phrase)}<X aria-hidden="true" className="size-3.5" /></button></li>)}
    </ul>}
  </div>;
}
