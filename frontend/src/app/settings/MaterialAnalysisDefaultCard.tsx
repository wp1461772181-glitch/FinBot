// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useEffect, useState } from "react";
import { getChatMode } from "../../api/base";
import { getMaterialAnalysisSettings, saveMaterialAnalysisSettings, resetMaterialAnalysisSettings, type MaterialAnalysisSettings } from "../../api/material-library";
import { getModelCatalog, type CatalogModel } from "../../api/bots";
import { useLocale } from "../../i18n";

export function MaterialAnalysisDefaultCard() {
  const { t } = useLocale();
  const [settings, setSettings] = useState<MaterialAnalysisSettings | null>(null);
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [selected, setSelected] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const personal = getChatMode() === "personal";
  useEffect(() => {
    let cancelled = false;
    getMaterialAnalysisSettings()
      .then((value) => { if (!cancelled) setSettings(value); })
      .catch((error: unknown) => { if (!cancelled) setStatus(error instanceof Error ? error.message : t("无法读取材料分析默认模型。")); });
    if (personal) getModelCatalog()
      .then((value) => { if (!cancelled) setModels(value.models.filter((item) => item.key_status === "configured")); })
      .catch(() => { /* the catalog card above reports it */ });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    if (settings?.source !== "settings") { setSelected(""); return; }
    const match = models.find((item) => item.provider === settings.provider && item.model === settings.model && (item.base_url || "") === (settings.base_url || ""));
    setSelected(match?.name ?? "");
  }, [settings, models]);
  if (!personal) return null;
  const current = settings?.source === "settings"
    ? `${settings.provider} · ${settings.model}`
    : `${t("系统 DeepSeek")} · ${settings?.model || "…"}`;
  async function apply() {
    setBusy(true);
    setStatus("");
    try {
      const next = selected ? await saveMaterialAnalysisSettings({ catalog_model: selected }) : await resetMaterialAnalysisSettings();
      setSettings(next);
      setStatus(t("已保存。下一次材料分析将使用这个默认模型。"));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t("保存失败，请重试。"));
    } finally {
      setBusy(false);
    }
  }
  return <section className="agent-settings-card" aria-labelledby="material-analysis-default-title">
    <h2 id="material-analysis-default-title">{t("材料分析默认模型")}</h2>
    <p>{t("AI 材料分析默认使用这里选的目录模型；在材料详情页也可以只针对一次分析临时选择其他模型。")}</p>
    <p><strong>{t("当前默认")}：</strong>{current}{settings?.has_api_key ? ` · ${t("API key 已保存")}${settings.api_key_last4 ? `（…${settings.api_key_last4}）` : ""}` : ` · ${t("使用服务端环境变量")}`}</p>
    <label>{t("默认模型")}<select value={selected} onChange={(event) => { setSelected(event.target.value); setStatus(""); }} disabled={busy}>
      <option value="">{t("系统默认（DeepSeek 环境配置）")}</option>
      {models.map((item) => <option key={item.name} value={item.name}>{item.display_name || item.name} · {item.model}</option>)}
    </select></label>
    <div className="chat-archive-tools">
      <button type="button" className="primary-action" disabled={busy} onClick={() => void apply()}>{busy ? t("正在保存…") : selected ? t("设为默认") : t("恢复系统默认")}</button>
    </div>
    {models.length === 0 && <small>{t("模型目录里还没有可用的模型；请先在上方添加并测试一个。")}</small>}
    {status && <p role="status">{status}</p>}
  </section>;
}
