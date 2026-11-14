// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useCallback, useEffect, useRef, useState } from "react";
import { addCatalogModel, deleteCatalogModel, discoverCatalogModels, getChatMode, getModelCatalog, getModelRoles, setDefaultCatalogModel, setModelRole, testCatalogModel, updateCatalogModel, type ModelCatalog } from "../../api";
import { catalogName, entryMoved, entryProblem, probeFor, saveBody, siblingsToInert, type CatalogEntryDraft } from "../../catalog-form.mjs";
import { createModelDiscoveryScheduler } from "../../model-discovery.mjs";
import { useLocale } from "../../i18n";
import { keyStatusLabel } from "../../bot-items.mjs";
import { CATALOG } from "../../model-profiles.mjs";
import { confirm } from "@/components/state/confirm";
import { message } from "../../bot-message";

const blankEntry = (taken: string[]): CatalogEntryDraft => ({ name: catalogName(CATALOG[0].provider, taken), display_name: "", provider: CATALOG[0].provider, model: "", base_url: CATALOG[0].baseUrl, key_mode: "vault", api_key: "", key_env: "", is_default: taken.length === 0, editing: null });
const DISCOVERY_ERRORS: Record<string, string> = { model_discovery_auth_required: "请填写此服务商的 API key 后重试。", model_discovery_access_denied: "当前 API key 无权读取模型列表。",
  model_discovery_rate_limited: "模型目录请求被限流，请稍后重试。", model_discovery_timeout: "获取模型列表超时，请稍后重试。" };


/** A model role (agent_model_roles): the catalog model that does one job; empty = the server default.
 *  earnings = 财报判断模型 (reads earnings releases); forecast = 预测模型 (gives the direction probabilities);
 *  judge = 审查模型 (the claim judge; unset falls back to the deployment's configured judge, not the catalog default). */
function RoleModelSelect({ catalog, role, label, hint, unsetLabel }: { catalog: ModelCatalog; role: "earnings" | "forecast" | "judge"; label: string; hint: string; unsetLabel?: string }) {
  const { t } = useLocale();
  const [chosen, setChosen] = useState<string>(""), [busy, setBusy] = useState(false), [note, setNote] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getModelRoles(controller.signal).then(r => { if (!controller.signal.aborted) setChosen(r.roles[role] ?? ""); }).catch(() => {});
    return () => controller.abort();
  }, [role]);
  const known = chosen === "" || catalog.models.some(m => m.name === chosen);
  async function change(value: string) {
    setBusy(true); setNote("");
    try { await setModelRole(role, value || null); setChosen(value); setNote(t("已保存。")); } catch (err) { setNote(message(err, t("保存失败。"))); } finally { setBusy(false); }
  }
  return <label className="earnings-model-select">{t(label)}
    <select disabled={busy} value={known ? chosen : ""} onChange={e => void change(e.target.value)}>
      <option value="">{unsetLabel ? t(unsetLabel) : <>{t("服务器默认模型")}{catalog.default ? ` (${catalog.default})` : ""}</>}</option>
      {catalog.models.map(m => <option key={m.name} value={m.name}>{m.display_name || m.name}</option>)}
    </select>
    <small>{t(hint)}</small>{note && <small role="status">{note}</small>}
  </label>;
}

/** Settings: the server's model catalog, the only place models are configured (UX batch 3: the browser model
 *  profiles are gone).  ＋ 添加模型 / 编辑 open the same dialog the browser profiles had — provider, Base URL, Model ID,
 *  服务商可用模型 with 刷新, key, 测试并保存 — but the key goes to the server once and is never read back. */
export function ModelCatalogCard() {
  const { t } = useLocale();
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null), [status, setStatus] = useState(""), [busy, setBusy] = useState(false), [entry, setEntry] = useState<CatalogEntryDraft | null>(null);
  const [testing, setTesting] = useState(false), [error, setError] = useState(""), [nameTouched, setNameTouched] = useState(false);
  const [candidates, setCandidates] = useState<Array<{ id: string; name: string }>>([]), [discoveryStatus, setDiscoveryStatus] = useState("");
  const modal = useRef<HTMLElement>(null), previous = useRef<HTMLElement | null>(null), testController = useRef<AbortController | null>(null), discovery = useRef<AbortController | null>(null);
  const scheduler = useRef(createModelDiscoveryScheduler());
  const load = useCallback(async () => { try { setCatalog(await getModelCatalog()); } catch (err) { setStatus(message(err, t("模型目录暂时无法读取。"))); } }, [t]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => { testController.current?.abort(); discovery.current?.abort(); scheduler.current.cancel(); }, []);
  const taken = (catalog?.models ?? []).map(m => m.name);
  async function fetchModels(current = entry) {
    discovery.current?.abort();
    const probe = probeFor(current, { forDiscovery: true });
    if (!current || !probe) { setCandidates([]); setDiscoveryStatus(t("填写 API key 后可获取模型列表")); return; }
    const controller = new AbortController(); discovery.current = controller;
    setDiscoveryStatus(t("正在获取服务商模型…"));
    try {
      const result = await discoverCatalogModels(probe, controller.signal);
      if (controller.signal.aborted) return;
      setCandidates(result.models.slice(0, 5));
      setDiscoveryStatus(result.status === "unsupported" ? t("该服务商没有可用的模型列表接口，可手动填写 Model ID") : result.models.length ? t("选择列表中的模型填入 Model ID") : t("服务商暂未返回可用模型，可手动填写 Model ID"));
    } catch (err) {
      if (controller.signal.aborted) return;
      setCandidates([]);
      const code = err instanceof Error ? err.message.replaceAll('"', "") : "";
      setDiscoveryStatus(t(DISCOVERY_ERRORS[code] ?? (err instanceof Error ? err.message : "暂时无法获取服务商模型列表。")));
    }
  }
  function open(next: CatalogEntryDraft) {
    previous.current = document.activeElement as HTMLElement; setEntry(next); setError(""); setNameTouched(Boolean(next.editing)); setCandidates([]); setDiscoveryStatus("");
    if (probeFor(next, { forDiscovery: true })) void fetchModels(next);
  }
  function close() {
    if (busy) return;
    testController.current?.abort(); discovery.current?.abort(); scheduler.current.cancel();
    setTesting(false); setEntry(null); setCandidates([]); setDiscoveryStatus(""); previous.current?.focus();
  }
  function update(patch: Partial<CatalogEntryDraft>, rediscover = false) {
    if (!entry) return;
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
  useEffect(() => {
    if (!entry) return;
    const el = modal.current, main = el?.closest("main.agent-admin");
    const inerted = siblingsToInert(main, el);
    inerted.forEach(x => x.setAttribute("inert", ""));
    el?.querySelector<HTMLElement>("input")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); close(); }
      if (e.key === "Tab" && el) {
        const items = [...el.querySelectorAll<HTMLElement>("button,input,select")].filter(x => !x.hasAttribute("disabled"));
        const first = items[0], last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); inerted.forEach(x => x.removeAttribute("inert")); };
  }, [Boolean(entry), busy]); // eslint-disable-line react-hooks/exhaustive-deps
  if (getChatMode() !== "personal") return null;
  async function run(work: () => Promise<unknown>, done: string) {
    setBusy(true); setStatus("");
    try { await work(); await load(); setStatus(t(done)); return true; } catch (err) { setStatus(message(err, t("保存失败。"))); return false; } finally { setBusy(false); }
  }
  async function testAndSave() {
    if (!entry) return;
    const problem = entryProblem(entry, taken);
    if (problem) { setError(t(problem)); return; }
    scheduler.current.cancel(); discovery.current?.abort();
    const controller = new AbortController(); testController.current = controller;
    setTesting(true); setBusy(true); setError("");
    try {
      await testCatalogModel(probeFor(entry)!, controller.signal);
      if (controller.signal.aborted) return;
      const body = saveBody(entry);
      // An edit names the entry by its stored name and sends the name it should have now: a rename when it changed.
      if (entry.editing) await updateCatalogModel(entry.editing.name, { ...body, name: entry.name }); else await addCatalogModel({ ...body, name: entry.name });
      await load();
      setStatus(t("已测试并保存。用它的 bot 下一轮生效。"));
      setEntry(null); previous.current?.focus();
    } catch (err) {
      if (!controller.signal.aborted) setError(message(err, t("连接失败，请重试")));
    } finally {
      if (testController.current === controller) testController.current = null;
      setTesting(false); setBusy(false);
    }
  }
  function cancelTest() { testController.current?.abort(); setTesting(false); setBusy(false); }
  const moved = entryMoved(entry);
  return <section className="agent-settings-card" aria-labelledby="model-catalog-title">
    <h2 id="model-catalog-title">{t("模型配置")}</h2>
    <p>{t("对话、bot、定时任务和材料分析都只用这里的模型。key 只发给服务器一次，加密保存或读服务器的环境变量；页面只显示「已配置」或「缺 key」，不会再显示 key。")}</p>
    {catalog?.config_file.present && <small>{t("服务器配置文件里的模型只能在服务器上改。")}{catalog.config_file.problems.length ? ` ${t("配置文件有问题")}：${catalog.config_file.problems.length}` : ""}</small>}
    {catalog && <div className="profile-grid">{catalog.models.map(m => <div key={m.name} className={`profile-card catalog-card ${m.is_default ? "is-active" : ""}`}>
      <span>{m.is_default ? <>★ {t("默认")}</> : t(m.origin === "server" ? "已保存" : "来自配置文件")}</span>
      <strong>{m.display_name || m.name}</strong>
      <small>{t(CATALOG.find(x => x.provider === m.provider)?.label ?? m.provider)} · {m.model}</small>
      <small><span className={`catalog-key ${m.key_status === "configured" ? "is-ready" : "is-missing"}`}>{t(keyStatusLabel(m))}</span>{m.key_source === "env" && m.key_env ? ` · ${t("环境变量")} ${m.key_env}` : ""} · {m.name}</small>
      {m.origin === "server" && <span className="catalog-actions">
        <button type="button" className="text-button" disabled={busy} onClick={() => open({ name: m.name, display_name: m.display_name, provider: m.provider, model: m.model, base_url: m.base_url ?? "", key_mode: m.key_source, api_key: "", key_env: m.key_env ?? "", is_default: m.is_default, editing: m })}>{t("编辑")}</button>
        {!m.is_default && <button type="button" className="text-button" disabled={busy} onClick={() => void run(() => setDefaultCatalogModel(m.name), "已设为默认模型。")}>{t("设为默认")}</button>}
        <button type="button" className="text-button" disabled={busy} onClick={async () => { if (await confirm({ title: `${t("删除模型")} ${m.display_name || m.name}？`, description: t("删除后这个模型会从模型目录里移除，不能恢复。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true })) void run(() => deleteCatalogModel(m.name), "已删除。"); }}>{t("删除")}</button>
      </span>}
    </div>)}
      <button type="button" disabled={busy} className="profile-card profile-add" onClick={() => open(blankEntry(taken))}><strong>{t("＋ 添加模型")}</strong><small>{t("添加一个已兼容的服务配置")}</small></button>
    </div>}
    {catalog && !catalog.models.length && <small>{t("目录是空的：先添加一个模型，bot 才能回答。")}</small>}
    {catalog && catalog.models.length > 0 && <RoleModelSelect catalog={catalog} role="earnings" label="财报判断模型" hint="读财报、判断涨跌用的模型；不选就用服务器默认模型。" />}
    {catalog && catalog.models.length > 0 && <RoleModelSelect catalog={catalog} role="forecast" label="预测模型" hint="给出 20 个交易日涨/平/跌概率的模型，建议选推理模型；不选就用服务器默认模型。" />}
    {catalog && catalog.models.length > 0 && <RoleModelSelect catalog={catalog} role="judge" label="审查模型" hint="回答之后核查其中论断与依据的模型；不选就用部署时配置的审查模型。" unsetLabel="部署配置的审查模型" />}
    {status && <p role="status">{status}</p>}
    {entry && <div className="profile-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}>
      <section ref={modal} className="profile-modal" role="dialog" aria-modal="true" aria-labelledby="catalog-entry-title">
        <button type="button" className="profile-close" onClick={close} aria-label={t("关闭")} disabled={busy}>×</button>
        <p className="eyebrow">{entry.editing ? t("编辑模型配置") : t("新建模型配置")}</p>
        <h2 id="catalog-entry-title">{entry.editing ? t("模型配置") : t("添加模型配置")}</h2>
        <label>{t("显示名称")}<input disabled={busy} value={entry.display_name} maxLength={80} onChange={e => update({ display_name: e.target.value })} placeholder={t("例如：财报研究助手")} /></label>
        <label>{t("模型服务")}<select disabled={busy} value={entry.provider} onChange={e => { const p = CATALOG.find(x => x.provider === e.target.value)!; update({ provider: p.provider, base_url: p.baseUrl, model: "", ...(entry.key_mode === "vault" ? { api_key: "" } : {}) }, true); }}>{CATALOG.map(x => <option key={x.provider} value={x.provider}>{t(x.label)}</option>)}</select></label>
        <label>{t("Base URL")}<input disabled={busy} value={entry.base_url} maxLength={2048} autoComplete="url" onChange={e => update({ base_url: e.target.value }, true)} /></label>
        <label>{t("Model ID")}<input disabled={busy} value={entry.model} maxLength={160} onChange={e => update({ model: e.target.value })} placeholder={t(CATALOG.find(x => x.provider === entry.provider)?.suggestion ?? "请输入 Model ID")} /></label>
        <label>{t("服务商可用模型")}<span className="model-discovery-row"><select disabled={busy} aria-label={t("服务商可用模型")} value="" onChange={e => { const item = candidates.find(x => x.id === e.target.value); if (item) update({ model: item.id }); }}><option value="" disabled>{t("选择列表中的模型填入 Model ID")}</option>{candidates.map(item => <option key={item.id} value={item.id}>{item.name === item.id ? item.id : `${item.name} · ${item.id}`}</option>)}</select><button type="button" className="secondary-action" disabled={busy} onClick={() => void fetchModels()}>{t("刷新")}</button></span>{discoveryStatus && <small role="status">{discoveryStatus}</small>}</label>
        <label>{t("key 从哪来")}<select disabled={busy} value={entry.key_mode} onChange={e => update({ key_mode: e.target.value as "vault" | "env" }, true)}><option value="vault">{t("在这里填，加密存进服务器")}</option><option value="env">{t("读服务器的环境变量")}</option></select></label>
        {entry.key_mode === "vault"
          ? <label>{t("API key")}<input disabled={busy} type="password" value={entry.api_key} maxLength={2048} autoComplete="new-password" onChange={e => update({ api_key: e.target.value }, true)} placeholder={entry.editing && !moved && entry.editing.key_status === "configured" ? t("不改就留空") : ""} /></label>
          : <label>{t("环境变量名")}<input disabled={busy} value={entry.key_env} maxLength={64} onChange={e => update({ key_env: e.target.value.toUpperCase() }, true)} placeholder="DEEPSEEK_API_KEY" /></label>}
        {moved && <small className="bot-warn">{t("换了服务或接口地址，需要重新填写 key。")}</small>}
        <label>{t("目录名（bot 用它引用这个模型）")}<input disabled={busy} value={entry.name} maxLength={40} onChange={e => { setNameTouched(true); setEntry({ ...entry, name: e.target.value.toLowerCase() }); }} /></label>
        {entry.editing && entry.name !== entry.editing.name && <small>{t("改名会同时更新用它的 bot，以及财报判断模型、预测模型、审查模型的设置。")}</small>}
        <label className="bot-check"><input type="checkbox" disabled={busy} checked={entry.is_default} onChange={e => update({ is_default: e.target.checked })} />{t("设为默认模型")}</label>
        <p className="profile-note">{t("测试并保存会用当前填写的服务、Model ID 和 key 在服务器上发一次简短请求；成功后才保存，用它的 bot 下一轮生效。")}</p>
        {error && <p className="agent-chat-status is-error" role="alert">{error}</p>}
        <button type="button" className="secondary-action" onClick={cancelTest} disabled={!testing}>{t("取消测试")}</button>
        <button type="button" className="primary-action" disabled={busy || Boolean(entryProblem(entry, taken))} onClick={() => void testAndSave()}>{testing ? t("正在测试…") : t("测试并保存")}</button>
      </section>
    </div>}
  </section>;
}
