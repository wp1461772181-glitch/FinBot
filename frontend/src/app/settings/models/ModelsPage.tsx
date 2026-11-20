import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { notify } from "@/components/state/notify";
import { deleteCatalogModel, getModelRoles, setDefaultCatalogModel, setModelRole } from "../../../api/catalog-admin";
import { getModelCatalog, type CatalogModel } from "../../../api/bots";
import { getMaterialAnalysisSettings, resetMaterialAnalysisSettings, saveMaterialAnalysisSettings, type MaterialAnalysisSettings } from "../../../api/material-library";
import { message } from "../../../bot-message";
import type { CatalogEntryDraft } from "../../../catalog-form.mjs";
import { useLocale, colon } from "../../../i18n";
import { useWorkspace } from "../../workspace";
import { useLoad } from "../../use-load";
import { SettingsCard } from "../SettingsCard";
import { SettingsGuestNote } from "../SettingsGuestNote";
import { ModelCard } from "./ModelCard";
import { RoleTable, type RoleKey } from "./RoleTable";
import { blankEntry, editEntry } from "./model-entry";

const ModelDialog = lazy(() => import("./ModelDialog"));

/** 模型 (#/settings/models, design 4.12): the server's model catalog (cards; 添加 / 编辑 in a dialog with 测试并保存) and, below it, the table of which model does which job.  The requests are the old page's. */
export function ModelsPage() {
  const { t } = useLocale();
  const { personal } = useWorkspace();
  if (!personal) return <SettingsGuestNote text={t("登录个人聊天后才能配置模型：对话、bot 和定时任务都用服务器模型目录里的模型。")} />;
  return <ModelsBody />;
}

function ModelsBody() {
  const { t } = useLocale();
  // One read of each: the old page asked for the catalog twice and for the roles three times.
  const catalogLoad = useLoad((signal) => getModelCatalog(signal));
  const rolesLoad = useLoad((signal) => getModelRoles(signal));
  const analysisLoad = useLoad((signal) => getMaterialAnalysisSettings(signal));
  const catalog = catalogLoad.data;
  const [roles, setRoles] = useState<Record<string, string | null>>({});
  const [analysis, setAnalysis] = useState<MaterialAnalysisSettings | null>(null);
  useEffect(() => { if (rolesLoad.data) setRoles(rolesLoad.data.roles); }, [rolesLoad.data]);
  useEffect(() => { if (analysisLoad.data) setAnalysis(analysisLoad.data); }, [analysisLoad.data]);
  const [busy, setBusy] = useState<string | null>(null), [roleBusy, setRoleBusy] = useState<RoleKey | null>(null), [failure, setFailure] = useState(""), [roleFailure, setRoleFailure] = useState("");
  const [dialog, setDialog] = useState<{ initial: CatalogEntryDraft; opener: HTMLElement | null } | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const taken = (catalog?.models ?? []).map((m) => m.name);
  const returnFocus = () => { const back = dialog?.opener?.isConnected ? dialog.opener : addButton.current; back?.focus(); };
  const here = () => (document.activeElement instanceof HTMLElement ? document.activeElement : null);

  async function act(id: string, work: () => Promise<unknown>, done: string) {
    setBusy(id); setFailure("");
    try { await work(); await catalogLoad.reload(); notify.success(t(done), { id: "settings:models" }); }
    catch (err) { setFailure(message(err, t("保存失败。"))); }
    finally { setBusy(null); }
  }
  async function remove(model: CatalogModel, from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: `${t("删除模型")} ${model.display_name || model.name}？`, description: t("删除后这个模型会从模型目录里移除，不能恢复。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (yes) await act(model.name, () => deleteCatalogModel(model.name), "已删除。");
  }
  async function changeRole(key: RoleKey, value: string | null) {
    setRoleBusy(key); setRoleFailure("");
    try {
      if (key === "chat") { await setDefaultCatalogModel(value!); await catalogLoad.reload(); notify.success(t("已设为默认模型。"), { id: "settings:roles" }); }
      else if (key === "analysis") { const next = value ? await saveMaterialAnalysisSettings({ catalog_model: value }) : await resetMaterialAnalysisSettings(); setAnalysis(next); notify.success(t("已保存。下一次材料分析将使用这个默认模型。"), { id: "settings:roles" }); }
      else { await setModelRole(key, value); setRoles((current) => ({ ...current, [key]: value })); notify.success(t("已保存。"), { id: "settings:roles" }); }
    } catch (err) { setRoleFailure(message(err, t("保存失败。"))); }
    finally { setRoleBusy(null); }
  }
  async function saved(entry: CatalogEntryDraft) {
    setDialog(null);
    // A rename follows into the roles on the server; the table takes it over here instead of asking again.
    const old = entry.editing?.name;
    if (old && old !== entry.name) setRoles((current) => Object.fromEntries(Object.entries(current).map(([role, name]) => [role, name === old ? entry.name : name])));
    await catalogLoad.reload();
    notify.success(t("已测试并保存。用它的 bot 下一轮生效。"), { id: "settings:models" });
  }

  const config = catalog?.config_file;
  return <div data-testid="settings-models-body" className="flex flex-col gap-5">
    <SettingsCard id="model-catalog" title={t("模型配置")} testid="catalog-card" description={t("对话、bot、定时任务和材料分析都只用这里的模型。key 只发给服务器一次，加密保存或读服务器的环境变量；页面只显示「已配置」或「缺 key」，不会再显示 key。")}
      actions={<Button ref={addButton} type="button" data-testid="model-new" className="max-sm:h-11" disabled={!catalog || busy !== null} onClick={() => setDialog({ initial: blankEntry(taken), opener: here() })}><Plus aria-hidden="true" />{t("添加模型")}</Button>}>
      {config?.present && <p data-testid="config-file-note" className="m-0 text-small text-muted-foreground">{t("服务器配置文件里的模型只能在服务器上改。")}{config.problems.length ? ` ${t("配置文件有问题")}${colon()}${config.problems.length}` : ""}</p>}
      {failure && <ErrorBar message={failure} />}
      {catalogLoad.error != null && <ErrorBar error={catalogLoad.error} onRetry={() => void catalogLoad.reload()} retrying={catalogLoad.loading} />}
      {!catalog && catalogLoad.loading && <DelayedSkeleton><div role="status" aria-busy="true" data-testid="models-skeleton" className="grid gap-3 sm:grid-cols-2"><span className="sr-only">{t("正在读取")}</span>{[0, 1].map((i) => <Skeleton key={i} className="h-28 w-full" />)}</div></DelayedSkeleton>}
      {catalog && catalog.models.length === 0 && <div data-testid="models-empty" className="rounded-md border border-line bg-background"><EmptyState title={t("目录是空的：先添加一个模型，bot 才能回答。")} action={{ label: t("添加模型"), onClick: () => setDialog({ initial: blankEntry(taken), opener: here() }) }} /></div>}
      {catalog && catalog.models.length > 0 && <ul data-testid="model-list" className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2">
        {catalog.models.map((m) => <li key={m.name} className="min-w-0"><ModelCard model={m} busy={busy !== null}
          onEdit={(from) => setDialog({ initial: editEntry(m), opener: from })} onDefault={() => void act(m.name, () => setDefaultCatalogModel(m.name), "已设为默认模型。")} onDelete={(from) => void remove(m, from)} /></li>)}
      </ul>}
    </SettingsCard>
    {catalog && <>
      {(rolesLoad.error != null || analysisLoad.error != null) && <ErrorBar error={rolesLoad.error ?? analysisLoad.error} onRetry={() => { void rolesLoad.reload(); void analysisLoad.reload(); }} />}
      {roleFailure && <ErrorBar message={roleFailure} />}
      <RoleTable catalog={catalog} roles={roles} analysis={analysis} busy={roleBusy} onChange={(key, value) => void changeRole(key, value)} />
    </>}
    {dialog && <Suspense fallback={null}><ModelDialog initial={dialog.initial} taken={taken} onClose={() => setDialog(null)} onSaved={(entry) => void saved(entry)} returnFocus={returnFocus} /></Suspense>}
  </div>;
}
