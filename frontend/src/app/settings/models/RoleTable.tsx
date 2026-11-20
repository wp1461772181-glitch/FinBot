import type { ReactNode } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { CatalogModel, ModelCatalog } from "../../../api/bots";
import type { MaterialAnalysisSettings } from "../../../api/material-library";
import { useLocale } from "../../../i18n";
import { SettingsCard } from "../SettingsCard";

const NONE = "__none__";   // Radix Select has no empty value: this stands for 不指定 / 系统默认

export type RoleKey = "chat" | "earnings" | "forecast" | "judge" | "analysis";
type Row = { key: RoleKey; label: string; hint: string; value: string; options: Array<{ value: string; label: ReactNode; disabled?: boolean }>; missing: boolean; extra?: ReactNode };

/** Which catalog entry the material-analysis default is: the one with the same provider, model and endpoint (the server stores those, not the catalog name); "" when it is the system's own. */
export function analysisChoice(settings: MaterialAnalysisSettings | null, models: CatalogModel[]): string {
  if (settings?.source !== "settings") return "";
  return models.find((m) => m.provider === settings.provider && m.model === settings.model && (m.base_url || "") === (settings.base_url || ""))?.name ?? "";
}

/**
 * 角色 → 模型 (design 4.12): the one table of which catalog model does which job.  Five rows, one choice each, and a choice is saved the moment it is made (no separate save button).
 * 对话默认 can only be one of the models saved on the server (a model from the catalog file is shown but cannot be picked); the three roles and the material-analysis default are the old cards', now in one place.
 */
export function RoleTable({ catalog, roles, analysis, busy, onChange }: { catalog: ModelCatalog; roles: Record<string, string | null>; analysis: MaterialAnalysisSettings | null; busy: RoleKey | null; onChange: (key: RoleKey, value: string | null) => void }) {
  const { t } = useLocale();
  const models = catalog.models;
  const byName = (name: string) => models.find((m) => m.name === name);
  const shown = (m: CatalogModel) => m.display_name || m.name;
  const roleOptions = (unset: ReactNode) => [{ value: NONE, label: unset }, ...models.map((m) => ({ value: m.name, label: shown(m) }))];
  const roleValue = (role: string) => { const v = roles[role] ?? ""; return v && byName(v) ? v : NONE; };
  const rows: Row[] = [];
  if (models.length) {
    rows.push({ key: "chat", label: "对话默认", hint: "没有指定模型的 bot 和对话用它。", value: catalog.default && byName(catalog.default) ? catalog.default : "", options: models.map((m) => ({ value: m.name, label: m.origin === "server" ? shown(m) : `${shown(m)} · ${t("来自配置文件")}`, disabled: m.origin !== "server" })), missing: byName(catalog.default ?? "")?.key_status === "missing" });
    const unsetDefault = <>{t("服务器默认模型")}{catalog.default ? ` (${catalog.default})` : ""}</>;
    rows.push({ key: "earnings", label: "财报判断模型", hint: "读财报、判断涨跌用的模型；不选就用服务器默认模型。", value: roleValue("earnings"), options: roleOptions(unsetDefault), missing: byName(roles.earnings ?? "")?.key_status === "missing" });
    rows.push({ key: "forecast", label: "预测模型", hint: "给出 20 个交易日涨/平/跌概率的模型，建议选推理模型；不选就用服务器默认模型。", value: roleValue("forecast"), options: roleOptions(unsetDefault), missing: byName(roles.forecast ?? "")?.key_status === "missing" });
    rows.push({ key: "judge", label: "审查模型", hint: "回答之后核查其中论断与依据的模型；不选就用部署时配置的审查模型。", value: roleValue("judge"), options: roleOptions(t("部署配置的审查模型")), missing: byName(roles.judge ?? "")?.key_status === "missing" });
  }
  const ready = models.filter((m) => m.key_status === "configured");
  const chosen = analysisChoice(analysis, models);
  // The words after 「当前默认」: provider and model, then whether the server holds a key for it.  The key itself (not even its last characters) is never shown.
  const current = analysis ? `${analysis.source === "settings" ? `${analysis.provider} · ${analysis.model}` : `${t("系统 DeepSeek")} · ${analysis.model || "…"}`}${analysis.has_api_key ? ` · ${t("API key 已保存")}` : ` · ${t("使用服务端环境变量")}`}` : "…";
  rows.push({ key: "analysis", label: "材料分析默认模型", hint: "AI 材料分析默认使用这里选的目录模型；在材料详情页也可以只针对一次分析临时选择其他模型。", value: chosen || NONE,
    options: [{ value: NONE, label: t("系统默认（DeepSeek 环境配置）") }, ...ready.map((m) => ({ value: m.name, label: `${shown(m)} · ${m.model}` }))], missing: false,
    extra: <>
      <p data-testid="analysis-current" className="m-0 text-small text-ink"><strong className="font-medium">{t("当前默认")}：</strong>{current}</p>
      {ready.length === 0 && <p data-testid="analysis-no-models" className="m-0 text-small text-muted-foreground">{t("模型目录里还没有可用的模型；请先在上方添加并测试一个。")}</p>}
    </> });
  return <SettingsCard id="roles" title={t("角色 → 模型")} testid="roles-card" description={t("每个角色用哪个模型，选了就保存，用它的 bot 下一轮生效。")}>
    <ul data-testid="roles-table" className="m-0 grid list-none divide-y divide-line p-0">
      {rows.map((row) => <li key={row.key} data-testid="role-row" data-role={row.key} className="grid gap-2 py-3 first:pt-0 last:pb-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] lg:items-start lg:gap-6">
        <div className="flex min-w-0 flex-col gap-1">
          <span id={`role-${row.key}-label`} className="text-small font-medium text-ink">{t(row.label)}</span>
          <p className="m-0 text-small text-muted-foreground">{t(row.hint)}</p>
          {row.extra}
          {row.missing && <p data-testid="role-missing-key" className="m-0 text-small text-ink">{t("这个模型缺 key，用到它的任务会失败。")}</p>}
        </div>
        <Select value={row.value} disabled={busy !== null} onValueChange={(value) => onChange(row.key, value === NONE ? null : value)}>
          <SelectTrigger aria-labelledby={`role-${row.key}-label`} data-testid={`role-${row.key}`} className="w-full max-lg:h-11"><SelectValue /></SelectTrigger>
          <SelectContent>{row.options.map((o) => <SelectItem key={o.value} value={o.value} disabled={o.disabled}>{o.label}</SelectItem>)}</SelectContent>
        </Select>
      </li>)}
    </ul>
  </SettingsCard>;
}
