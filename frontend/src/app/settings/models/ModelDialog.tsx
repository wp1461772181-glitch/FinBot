// The add / edit dialog of a catalog model (P8.2, design 4.12): a dialog on a wide screen, a drawer below 1024, one body in both.  The draft (the fields, the candidates, the test) is held HERE, outside the two shells,
// so crossing the breakpoint with the dialog open keeps what was typed.  A chunk of its own: the page only fetches it when 添加模型 / 编辑 is pressed.
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Eye, EyeOff, X } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerDescription, DrawerTitle } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton, type ButtonPhase } from "@/components/state/StatefulButton";
import { addCatalogModel, discoverCatalogModels, testCatalogModel, updateCatalogModel } from "../../../api/catalog-admin";
import { catalogName, entryMoved, entryProblem, probeFor, saveBody, type CatalogEntryDraft } from "../../../catalog-form.mjs";
import { createModelDiscoveryScheduler } from "../../../model-discovery.mjs";
import { ModelPicker } from "./ModelPicker";
import { message } from "../../../bot-message";
import { useLocale } from "../../../i18n";
import { CATALOG } from "../../../model-profiles.mjs";

const WIDE_QUERY = "(min-width: 1024px)";
const subscribeWide = (notify: () => void) => { const list = window.matchMedia?.(WIDE_QUERY); list?.addEventListener?.("change", notify); return () => list?.removeEventListener?.("change", notify); };
const useWide = () => useSyncExternalStore(subscribeWide, () => window.matchMedia?.(WIDE_QUERY).matches ?? false, () => false);

/** The sentences of the server's four refusals of 服务商可用模型 (the codes are matched against the error's own text; any other error shows its own words). */
export const DISCOVERY_ERRORS: Record<string, string> = { model_discovery_auth_required: "请填写此服务商的 API key 后重试。", model_discovery_access_denied: "当前 API key 无权读取模型列表。",
  model_discovery_rate_limited: "模型目录请求被限流，请稍后重试。", model_discovery_timeout: "获取模型列表超时，请稍后重试。" };

const PRICE_BOXES = [["price_input", "输入价格"], ["price_output", "输出价格"], ["price_cache_read", "缓存读取价格"], ["price_cache_write", "缓存写入价格"]] as const;
type Props = { initial: CatalogEntryDraft; taken: string[]; onClose: () => void; onSaved: (entry: CatalogEntryDraft) => void; returnFocus: () => void };

export default function ModelDialog({ initial, taken, onClose, onSaved, returnFocus }: Props) {
  const { t } = useLocale();
  const wide = useWide();
  const [entry, setEntry] = useState<CatalogEntryDraft>(initial), [nameTouched, setNameTouched] = useState(Boolean(initial.editing));
  const [candidates, setCandidates] = useState<Array<{ id: string; name: string }>>([]), [discoveryStatus, setDiscoveryStatus] = useState("");
  const [showKey, setShowKey] = useState(false), [error, setError] = useState(""), [testing, setTesting] = useState(false), [phase, setPhase] = useState<ButtonPhase>("idle");
  const testController = useRef<AbortController | null>(null), discovery = useRef<AbortController | null>(null), scheduler = useRef(createModelDiscoveryScheduler());
  const resetTimer = useRef<number | undefined>(undefined), content = useRef<HTMLDivElement>(null);

  async function fetchModels(current: CatalogEntryDraft) {
    discovery.current?.abort();
    const probe = probeFor(current, { forDiscovery: true });
    if (!probe) { setCandidates([]); setDiscoveryStatus(t("填写 API key 后可获取模型列表")); return; }
    const controller = new AbortController(); discovery.current = controller;
    setDiscoveryStatus(t("正在获取服务商模型…"));
    try {
      const result = await discoverCatalogModels(probe, controller.signal);
      if (controller.signal.aborted) return;
      setCandidates(result.models);
      setDiscoveryStatus(result.status === "unsupported" ? t("该服务商没有可用的模型列表接口，可手动填写 Model ID") : result.models.length ? t(result.truncated ? "模型太多，只列出最新的一部分；找不到的可手动填写 Model ID" : "选择列表中的模型填入 Model ID") : t("服务商暂未返回可用模型，可手动填写 Model ID"));
    } catch (err) {
      if (controller.signal.aborted) return;
      setCandidates([]);
      const code = err instanceof Error ? err.message.replaceAll('"', "") : "";
      setDiscoveryStatus(t(DISCOVERY_ERRORS[code] ?? (err instanceof Error ? err.message : "暂时无法获取服务商模型列表。")));
    }
  }
  // Opening an entry that can already be asked (it has a stored key, or the provider needs none) lists the provider's models at once.
  useEffect(() => { if (probeFor(initial, { forDiscovery: true })) void fetchModels(initial); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { testController.current?.abort(); discovery.current?.abort(); scheduler.current.cancel(); window.clearTimeout(resetTimer.current); }, []);

  function update(patch: Partial<CatalogEntryDraft>, rediscover = false) {
    const next = { ...entry, ...patch };
    if (!nameTouched && !next.editing && ("display_name" in patch || "model" in patch || "provider" in patch)) next.name = catalogName(next.display_name || next.model || next.provider, taken);
    setEntry(next);
    if (rediscover) {
      discovery.current?.abort(); setCandidates([]);
      scheduler.current.setContext(`${next.provider}:${next.base_url}:${next.key_mode}`);
      if (probeFor(next, { forDiscovery: true })) { setDiscoveryStatus(t("输入完成后将自动获取模型列表")); scheduler.current.schedule(() => void fetchModels(next)); }
      else setDiscoveryStatus(t("填写 API key 后可获取模型列表"));
    }
  }
  const problem = entryProblem(entry, taken);
  const moved = entryMoved(entry);
  async function testAndSave() {
    if (testing) return;
    if (problem) { setError(t(problem)); return; }
    scheduler.current.cancel(); discovery.current?.abort();
    const controller = new AbortController(); testController.current = controller;
    window.clearTimeout(resetTimer.current);
    setTesting(true); setPhase("loading"); setError("");
    try {
      await testCatalogModel(probeFor(entry)!, controller.signal);
      if (controller.signal.aborted) return;
      const body = saveBody(entry);
      // An edit names the entry by its stored name and sends the name it should have now: a rename when it changed.
      if (entry.editing) await updateCatalogModel(entry.editing.name, { ...body, name: entry.name }); else await addCatalogModel({ ...body, name: entry.name });
      setPhase("success");
      onSaved(entry);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(message(err, t("连接失败，请重试")));
      setPhase("error");
      resetTimer.current = window.setTimeout(() => setPhase("idle"), 1600);
    } finally {
      if (testController.current === controller) testController.current = null;
      setTesting(false);
    }
  }
  function cancelTest() { testController.current?.abort(); setTesting(false); setPhase("idle"); }
  const close = (open: boolean) => { if (!open && !testing) { testController.current?.abort(); discovery.current?.abort(); scheduler.current.cancel(); onClose(); } };
  const giveBackFocus = (event: Event) => { event.preventDefault(); returnFocus(); };

  const field = (id: string) => `model-${id}`;
  const provider = CATALOG.find((x) => x.provider === entry.provider);
  // An edit shows the head and tail of the key kept on the server (key_hint); the whole key is never sent back.
  const keyHint = entry.editing?.key_hint;
  const keyPlaceholder = entry.editing && !moved && entry.editing.key_status === "configured" ? (keyHint ? t("当前：{key}，不改就留空").replace("{key}", keyHint) : t("不改就留空")) : "";
  const title = entry.editing ? t("编辑模型配置") : t("添加模型配置");
  const description = entry.editing ? t("模型配置") : t("添加一个已兼容的服务配置");
  const body = <div data-testid="model-form" className="flex min-h-0 flex-1 flex-col" onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && e.target instanceof HTMLInputElement && !problem && !testing) { e.preventDefault(); void testAndSave(); } }}>
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pt-4 pb-4 lg:px-6">
      <Field><FieldLabel htmlFor={field("display")}>{t("显示名称")}</FieldLabel>
        <Input id={field("display")} data-testid="model-display" className="max-lg:h-11" disabled={testing} value={entry.display_name} maxLength={80} autoComplete="off" onChange={(e) => update({ display_name: e.target.value })} placeholder={t("例如：财报研究助手")} /></Field>
      <Field><FieldLabel htmlFor={field("provider")}>{t("模型服务")}</FieldLabel>
        <Select value={entry.provider} disabled={testing} onValueChange={(value) => { const p = CATALOG.find((x) => x.provider === value)!; update({ provider: p.provider, base_url: p.baseUrl, model: "", ...(entry.key_mode === "vault" ? { api_key: "" } : {}) }, true); }}>
          <SelectTrigger id={field("provider")} data-testid="model-provider" className="w-full max-lg:h-11"><SelectValue /></SelectTrigger>
          <SelectContent>{CATALOG.map((x) => <SelectItem key={x.provider} value={x.provider}>{t(x.label)}</SelectItem>)}</SelectContent>
        </Select></Field>
      <Field><FieldLabel htmlFor={field("base-url")}>{t("Base URL")}</FieldLabel>
        <Input id={field("base-url")} data-testid="model-base-url" className="max-lg:h-11" disabled={testing} value={entry.base_url} maxLength={2048} autoComplete="url" onChange={(e) => update({ base_url: e.target.value }, true)} /></Field>
      <Field><FieldLabel htmlFor={field("model")}>{t("Model ID")}</FieldLabel>
        <Input id={field("model")} data-testid="model-id" className="max-lg:h-11" disabled={testing} value={entry.model} maxLength={160} autoComplete="off" onChange={(e) => update({ model: e.target.value })} placeholder={t(provider?.suggestion ?? "请输入 Model ID")} /></Field>
      <Field><FieldLabel id={field("discovered-label")}>{t("服务商可用模型")}</FieldLabel>
        <div className="flex items-center gap-2">
          <ModelPicker candidates={candidates} current={entry.model} disabled={testing} labelledBy={field("discovered-label")} onPick={(id) => update({ model: id })} />
          <Button type="button" variant="outline" data-testid="model-refresh" className="max-lg:h-11" disabled={testing} onClick={() => void fetchModels(entry)}>{t("刷新")}</Button>
        </div>
        {discoveryStatus && <FieldDescription role="status" data-testid="model-discovery-status">{discoveryStatus}</FieldDescription>}</Field>
      <Field><FieldLabel htmlFor={field("key-mode")}>{t("key 从哪来")}</FieldLabel>
        <Select value={entry.key_mode} disabled={testing} onValueChange={(value) => update({ key_mode: value as "vault" | "env" }, true)}>
          <SelectTrigger id={field("key-mode")} data-testid="model-key-mode" className="w-full max-lg:h-11"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="vault">{t("在这里填，加密存进服务器")}</SelectItem><SelectItem value="env">{t("读服务器的环境变量")}</SelectItem></SelectContent>
        </Select></Field>
      {entry.key_mode === "vault"
        ? <Field><FieldLabel htmlFor={field("key")}>{t("API key")}</FieldLabel>
          <div className="relative"><Input id={field("key")} data-testid="model-key" className="pr-11 max-lg:h-11" type={showKey ? "text" : "password"} disabled={testing} value={entry.api_key} maxLength={2048} autoComplete="new-password" autoCapitalize="off" spellCheck={false} onChange={(e) => update({ api_key: e.target.value }, true)} placeholder={keyPlaceholder} />
            <Button type="button" variant="ghost" size="icon" data-testid="model-key-toggle" aria-label={t(showKey ? "隐藏 API key" : "显示 API key")} aria-pressed={showKey} className="absolute top-0 right-0 size-9 max-lg:size-11" onClick={() => setShowKey(!showKey)}>{showKey ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}</Button></div></Field>
        : <Field><FieldLabel htmlFor={field("key-env")}>{t("环境变量名")}</FieldLabel>
          <Input id={field("key-env")} data-testid="model-key-env" className="max-lg:h-11" disabled={testing} value={entry.key_env} maxLength={64} autoComplete="off" onChange={(e) => update({ key_env: e.target.value.toUpperCase() }, true)} placeholder="DEEPSEEK_API_KEY" /></Field>}
      {moved && <p data-testid="model-moved-note" className="text-small text-ink">{t("换了服务或接口地址，需要重新填写 key。")}</p>}
      <Field><FieldLabel htmlFor={field("name")}>{t("目录名（bot 用它引用这个模型）")}</FieldLabel>
        <Input id={field("name")} data-testid="model-name" className="max-lg:h-11" disabled={testing} value={entry.name} maxLength={40} autoComplete="off" onChange={(e) => { setNameTouched(true); setEntry({ ...entry, name: e.target.value.toLowerCase() }); }} />
        {entry.editing && entry.name !== entry.editing.name && <FieldDescription data-testid="model-rename-note">{t("改名会同时更新用它的 bot，以及财报判断模型、预测模型、审查模型的设置。")}</FieldDescription>}</Field>
      <div className="flex items-center gap-3"><Switch id={field("default")} data-testid="model-default" disabled={testing} checked={entry.is_default} onCheckedChange={(checked) => update({ is_default: checked })} /><label htmlFor={field("default")} className="text-small text-ink">{t("设为默认模型")}</label></div>
      <fieldset data-testid="model-prices" className="flex flex-col gap-3" disabled={testing}>
        <legend className="mb-1 text-small font-medium text-ink">{t("价格（可选）")}</legend>
        <p className="text-small text-muted-foreground">{t("填了才会在后台算花费；不填只显示用量。")}</p>
        <div className="grid grid-cols-2 gap-3">
          {PRICE_BOXES.map(([name, label]) => <Field key={name}><FieldLabel htmlFor={field(name)}>{t(label)}</FieldLabel>
            <Input id={field(name)} data-testid={field(name)} className="max-lg:h-11" type="number" inputMode="decimal" min={0} step="any" value={entry[name]} autoComplete="off" onChange={(e) => update({ [name]: e.target.value } as Partial<CatalogEntryDraft>)} /></Field>)}
        </div>
        <FieldDescription>{t("单位：美元 / 百万 token。缓存价格不填时按输入价格算。")}</FieldDescription>
      </fieldset>
      <p className="text-small text-muted-foreground">{t("测试并保存会用当前填写的服务、Model ID 和 key 在服务器上发一次简短请求；成功后才保存，用它的 bot 下一轮生效。")}</p>
      {error && <ErrorBar message={error} />}
    </div>
    <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3 lg:px-6">
      <Button type="button" variant="outline" data-testid="model-cancel-test" className="max-lg:h-11" onClick={cancelTest} disabled={!testing}>{t("取消测试")}</Button>
      <StatefulButton type="button" data-testid="model-test-save" className="max-lg:h-11" phase={phase} resetAfter={1600} disabled={Boolean(problem) && !testing} onClick={() => void testAndSave()}>{t("测试并保存")}</StatefulButton>
    </div>
  </div>;
  const shell = (titleNode: ReactNode, descriptionNode: ReactNode) => <>{titleNode}{descriptionNode}{body}</>;
  if (wide) {
    return <Dialog open onOpenChange={close}>
      <DialogContent closeLabel={t("关闭")} data-testid="model-dialog" ref={content} className="flex max-h-[min(90dvh,820px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[560px]"
        onOpenAutoFocus={(event) => { event.preventDefault(); content.current?.querySelector<HTMLElement>("#model-display")?.focus(); }} onCloseAutoFocus={giveBackFocus}
        onEscapeKeyDown={(event) => { if (testing) event.preventDefault(); }} onInteractOutside={(event) => { if (testing) event.preventDefault(); }}>
        {shell(<div className="px-6 pt-5 pr-12"><DialogTitle className="text-title-s font-semibold text-ink">{title}</DialogTitle><DialogDescription className="text-small text-muted-foreground">{description}</DialogDescription></div>, null)}
      </DialogContent>
    </Dialog>;
  }
  return <Drawer open onOpenChange={close} dismissible={!testing} handleOnly>
    <DrawerContent data-testid="model-dialog" ref={content} className="data-[vaul-drawer-direction=bottom]:mt-0 data-[vaul-drawer-direction=bottom]:h-dvh data-[vaul-drawer-direction=bottom]:max-h-dvh data-[vaul-drawer-direction=bottom]:rounded-none"
      onOpenAutoFocus={(event) => { event.preventDefault(); content.current?.focus(); }} onCloseAutoFocus={giveBackFocus}>
      {shell(<div className="flex items-center justify-between gap-2 border-b border-line py-2 pr-2 pl-4"><div className="min-w-0"><DrawerTitle className="text-title-s font-semibold text-ink">{title}</DrawerTitle><DrawerDescription className="text-small text-muted-foreground">{description}</DrawerDescription></div>
        <Button type="button" variant="ghost" size="icon" className="size-11" disabled={testing} onClick={() => close(false)} aria-label={t("关闭")}><X aria-hidden="true" /></Button></div>, null)}
    </DrawerContent>
  </Drawer>;
}
