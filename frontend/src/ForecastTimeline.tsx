import { Tx, translatePhrase, useLocale } from "./i18n";
import type { V2ForecastRoots, V2Timeline, V2TimelineEntry, V2VersionDetail } from "./types";
import { forecastCopy, hasDecisionProbabilities, modelChanged } from "./forecast-model.mjs";
import { evidenceTitle, processingStatus, sourceKey } from "./EvidenceProcessing";
import { ProbabilityStrip, formatTime, modelStatusText } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";

export function RootPicker({ roots, selectedRootId, onSelect }: { roots: ResourceState<V2ForecastRoots>; selectedRootId: string; onSelect: (id: string) => void }) {
  const { t } = useLocale();
  if (roots.kind === "loading") return <p className="v2-root-loading">{<Tx text={"正在读取可修订的预测记录…"} />}</p>;
  if (roots.kind === "error") return <p className="v2-notice error" role="alert">{roots.message}</p>;
  if (!roots.data.roots.length) return <p className="v2-root-loading">{<Tx text={"尚无预测记录。任务成功发布后会出现在这里。"} />}</p>;
  return <label className="v2-root-picker">{<Tx text={"选择预测链（固定目标）"} />}<select value={selectedRootId} onChange={(event) => onSelect(event.target.value)}>
      {roots.data.roots.map((root) => <option value={root.id} key={root.id}>{formatTime(root.decision_at)} · {t("目标")} {root.target_end_date} · {t("第")} {root.latest_version_no} {t("版")}{root.expired === true ? ` · ${t("已到期")}` : root.expired === null ? ` · ${t("目标日期无效")}` : ""}</option>)}
    </select>
  </label>;
}

export function VersionPicker({ timeline, selectedVersionId, onSelect }: {
  timeline: ResourceState<V2Timeline> | null;
  selectedVersionId: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useLocale();
  if (timeline?.kind === "loading") return <p className="v2-root-loading">{<Tx text={"正在读取此预测链的版本结果…"} />}</p>;
  if (timeline?.kind === "error") return <p className="v2-notice error" role="alert">{t("无法读取版本结果：")}{timeline.message}</p>;
  const versions = timeline?.kind === "ready" ? timeline.data.versions : [];
  if (!versions.length) return null;
  return <label className="v2-root-picker">{<Tx text={"查看哪个版本的预测结果"} />}<select value={selectedVersionId} onChange={(event) => onSelect(event.target.value)}>
      {versions.map((version) => <option value={version.id} key={version.id}>
        {t("第")} {version.version_no} {t("版")} · {t(version.parent_version_id ? "修订" : "初始")} · {formatTime(version.decision_at)} · {versionProbabilityText(version)}
      </option>)}
    </select>
  </label>;
}

function versionProbabilityText(version: V2TimelineEntry) {
  const probabilities = hasDecisionProbabilities(version.model_status)
    ? version.decision_probabilities
    : version.model_status === "experimental_joint" ? version.joint_probabilities : null;
  if (!probabilities) return modelStatusText(version.model_status);
  return `${translatePhrase("跌")} ${Math.round(probabilities.bearish * 100)}% · ${translatePhrase("平")} ${Math.round(probabilities.neutral * 100)}% · ${translatePhrase("涨")} ${Math.round(probabilities.bullish * 100)}%`;
}

export function RevisionComparison({ timeline, detail }: { timeline: ResourceState<V2Timeline> | null; detail: ResourceState<{ current: V2VersionDetail; parent: V2VersionDetail | null }> | null }) {
  const { locale, t } = useLocale();
  if (timeline?.kind === "loading") return <section className="v2-card"><p>{<Tx text={"正在读取版本链…"} />}</p></section>;
  if (timeline?.kind === "error") return <section className="v2-card"><p>{t("版本链读取失败：")}{timeline.message}</p></section>;
  const versions = timeline?.kind === "ready" ? timeline.data.versions : [];
  const marketChanged = detail?.kind === "ready" && detail.data.parent
    ? marketSummary(detail.data.current.price_input_manifest) !== marketSummary(detail.data.parent.price_input_manifest)
    : false;
  return <section className="v2-card"><p className="section-label">{<Tx text={"修订对比"} />}</p><h3>{versions.length ? locale === "en-US" ? `${versions.length} historical ${versions.length === 1 ? "version" : "versions"}` : `${versions.length} ${t("个历史版本")}` : t("尚无版本链")}</h3>
    {versions.length > 1 ? <p>{<Tx text={"每个子版本保留固定目标合同；版本差异见下方事件记录。"} />}</p> : <p>{<Tx text={"出现新的合规材料后，可以从这里选择版本发起人工修订。"} />}</p>}
    {versions.length > 0 && <dl><div><dt>{<Tx text={"固定目标"} />}</dt><dd>{String(timeline?.kind === "ready" ? timeline.data.target_contract.target_end_date ?? t("已记录") : "—")}</dd></div><div><dt>{<Tx text={"当前版本"} />}</dt><dd>{t("第")} {versions.at(-1)?.version_no} {t("版")}</dd></div></dl>}
    {detail?.kind === "ready" && modelChanged(detail.data.current, detail.data.parent) && <p className="v2-limit v2-model-change">{t("决策模型与上一版不同：概率变化可能来自模型，不一定来自新材料。")}</p>}
    {detail?.kind === "ready" && detail.data.parent && <p className="v2-limit">{locale === "en-US" ? `${t("市场输入：")} ${marketChanged ? t("已更新（见下方截止时间）") : t("与父版清单一致")}. ${t("本系统尚未验证各输入对市场结果的定量归因。")}` : `${t("市场输入：")}${marketChanged ? t("已更新（见下方截止时间）") : t("与父版清单一致")}。${t("本系统尚未验证各输入对市场结果的定量归因。")}`}</p>}
  </section>;
}

export function EvidenceEvents({ timeline, detail, selectedVersionId, onSelect, showSourceDetail = true }: {
  timeline: ResourceState<V2Timeline> | null;
  detail: ResourceState<{ current: V2VersionDetail; parent: V2VersionDetail | null }> | null;
  selectedVersionId: string;
  onSelect: (id: string) => void;
  /** The single-forecast page keeps the source diffs in its collapsed 审计与来源 instead. */
  showSourceDetail?: boolean;
}) {
  const { locale, t } = useLocale();
  if (timeline?.kind !== "ready" || timeline.data.versions.length === 0) return null;
  return <section className="v2-events" aria-labelledby="v2-events-title"><div className="section-heading"><div><p className="eyebrow">{<Tx text={"版本与来源"} />}</p><h2 id="v2-events-title">{<Tx text={"预测版本记录"} />}</h2></div><span>{<Tx text={"同一固定目标"} />}</span></div>
  {detail?.kind === "ready" && modelChanged(detail.data.current, detail.data.parent) && <p className="v2-limit v2-model-change">{t("决策模型与上一版不同：概率变化可能来自模型，不一定来自新材料。")}</p>}
  <ol>
    {timeline.data.versions.map((version) => <li key={version.id} className={version.id === selectedVersionId ? "is-selected" : ""}>
      <span className="v2-event-dot" aria-hidden="true" />
      <button type="button" className="v2-event-select" onClick={() => onSelect(version.id)}><strong>{t("第")} {version.version_no} {t("版")} · {t(version.parent_version_id ? "修订版本" : "初始版本")}</strong><p>{formatTime(version.decision_at)} · {modelStatusText(version.model_status)} · {triggerTypeText(version.trigger_type)}</p>{version.change_reason && <small>{changeReasonText(version.change_reason, locale)}</small>}</button>
      {hasDecisionProbabilities(version.model_status) && version.decision_probabilities && <div className="v2-timeline-probabilities"><ProbabilityStrip probabilities={version.decision_probabilities} label={t(forecastCopy({ model_status: version.model_status }).timelineStripLabel)} compact /></div>}
      {version.model_status === "experimental_joint" && version.joint_probabilities && <ProbabilityStrip probabilities={version.joint_probabilities} label={t("实验性联合概率")} compact />}
    </li>)}
  </ol>{showSourceDetail && <EvidenceDetail detail={detail} />}</section>;
}

function changeReasonText(reason: string, locale: "zh-CN" | "en-US") {
  if (reason === "new forecast with frozen observed market and evidence inputs") {
    return locale === "en-US"
      ? "New forecast using a frozen snapshot of the available market data and sources."
      : "新建预测：冻结当时可用的行情和来源快照。";
  }
  const revision = reason.match(/^(manual_revision|automatic_revision): inherited frozen evidence plus (\d+) new or changed observed event\(s\)$/);
  if (!revision) return reason;
  const count = Number(revision[2]);
  if (locale === "en-US") {
    const kind = revision[1] === "manual_revision" ? "Manual revision" : "Automatic revision";
    return `${kind}: carried forward the prior frozen sources and added ${count} new or changed observed ${count === 1 ? "event" : "events"}.`;
  }
  const kind = revision[1] === "manual_revision" ? "人工修订" : "自动修订";
  return `${kind}：继承原冻结来源，并新增或更新了 ${count} 项可观察事件。`;
}

// The saved-inputs detail (source diffs, hashes) is one block that also carries the count header, so it stays here
// whole; B9 splits the audit part out when it builds the single-forecast page.
export function EvidenceDetail({ detail }: { detail: ResourceState<{ current: V2VersionDetail; parent: V2VersionDetail | null }> | null }) {
  const { locale, t } = useLocale();
  if (detail?.kind === "loading") return <p className="v2-detail-loading">{<Tx text={"正在读取所选版本的保存来源和市场输入…"} />}</p>;
  if (detail?.kind === "error") return <p className="v2-notice error" role="alert">{detail.message}</p>;
  if (detail?.kind !== "ready") return null;
  const { current, parent } = detail.data;
  const countLabel = (count: number) => locale === "en-US"
    ? `${count} ${count === 1 ? "material" : "materials"}`
    : `${count} ${t("条")}`;
  const currentSources = current.evidence_version_manifest;
  const parentSources = parent?.evidence_version_manifest ?? [];
  const parentBySource = new Map(parentSources.map((item) => [sourceIdentity(item), item]));
  const currentSourceKeys = new Set(currentSources.map(sourceIdentity));
  const added = currentSources.filter((item) => !parentBySource.has(sourceIdentity(item)));
  const replaced = currentSources.filter((item) => {
    const prior = parentBySource.get(sourceIdentity(item));
    return prior !== undefined && eventIdentity(prior) !== eventIdentity(item);
  });
  const removed = parentSources.filter((item) => !currentSourceKeys.has(sourceIdentity(item)));
  const inherited = currentSources.length - added.length - replaced.length;
  const explicitlySelected = explicitSourceKeys(current.research_report);
  const explicitCount = currentSources.filter((item) => explicitlySelected.has(sourceIdentity(item))).length;
  const automaticAddedCount = added.filter((item) => !explicitlySelected.has(sourceIdentity(item))).length;
  const market = current.price_input_manifest;
  const researchStatus = researchStatusText(current.research_report?.research_conclusions_status ?? current.research_report?.status);
  const brief = current.research_brief ?? null;
  const includedKeys = new Set((brief?.material_refs ?? []).map(sourceKey));
  const includedCount = currentSources.filter((item) => includedKeys.has(sourceKey(item))).length;
  return <section className="v2-detail" aria-label={t("所选版本的保存的输入")}>
    <div><p className="section-label">{t("所选第")} {current.version_no} {t("版的来源差异")}</p><h3>{parent ? `${t("新增")} ${added.length} · ${t("状态替换")} ${replaced.length} · ${t("移除")} ${removed.length} · ${t("继承")} ${inherited}` : locale === "en-US" ? `Frozen candidates: ${countLabel(currentSources.length)}` : `${t("冻结候选")} ${countLabel(currentSources.length)}`}</h3><p>{parent ? locale === "en-US" ? `Source composition: ${countLabel(inherited)} inherited from the parent, ${countLabel(explicitCount)} manually selected, and ${countLabel(automaticAddedCount)} automatically added by the system.` : `${t("本版来源构成：父版继承")} ${inherited} ${t("条，人工选入")} ${explicitCount} ${t("条，系统自动新增")} ${automaticAddedCount} ${t("条。")}` : t("初始版本没有父版本可比较。")}</p></div>
    <div className="v2-detail-material-counts"><strong>{brief ? locale === "en-US" ? `Actually cited in the brief: ${countLabel(includedCount)}` : `${t("简报实际引用")} ${countLabel(includedCount)}` : t("该版本未保存简报引用")}</strong><span>{brief ? locale === "en-US" ? `Not included in the brief: ${countLabel(Math.max(0, currentSources.length - includedCount))}. The frozen list records candidate sources available at the time; it does not mean every source was analyzed or entered the brief.` : `${t("未进入简报")} ${countLabel(Math.max(0, currentSources.length - includedCount))}。冻结清单记录当时的候选来源，不表示这些来源都被分析或进入了简报。` : t("没有简报记录时，无法从此版本确认哪些材料完成了分析。")}</span></div>
    <dl><div><dt>{<Tx text={"行情数据截止"} />}</dt><dd>{formatTime(String(market.market_cutoff_at ?? current.market_cutoff_at))}</dd></div><div><dt>{<Tx text={"最近完整交易日"} />}</dt><dd>{String(market.latest_completed_session ?? "未记录")}</dd></div><div><dt>{<Tx text={"价格输入哈希"} />}</dt><dd>{shortHash(market.price_input_sha256)}</dd></div><div><dt>{<Tx text={"研究报告"} />}</dt><dd>{researchStatus}</dd></div></dl>
    <div className="v2-source-list">{currentSources.length ? currentSources.map((item, index) => {
      const sourceUrl = typeof item.source_url === "string" ? item.source_url : null;
      const publishedAt = item.published_at ?? item.public_at;
      const key = sourceIdentity(item);
      const status = processingStatus(item, brief, t);
      const sourceOrigin = explicitlySelected.has(key)
        ? t("人工选入")
        : parent && parentBySource.has(key)
          ? item.is_new ? t("系统记录状态变化") : t("从父版继承")
          : parent ? t("系统自动纳入") : t("初始预测自动纳入");
      return <article key={`${eventIdentity(item)}-${index}`}><strong>{evidenceTitle(item, brief?.material_refs.find((ref) => sourceKey(ref) === sourceKey(item)))}</strong>{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer">{<Tx text={"打开原始来源"} />}</a> : <span>{<Tx text={"原始来源链接未记录"} />}</span>}<p>{formatTime(typeof publishedAt === "string" ? publishedAt : null)} · {coverageText(item.coverage_incomplete)}</p><span className={`evidence-processing-badge is-${status.tone}`}>{status.label}</span><small>{status.detail}</small><small>{sourceOrigin} · {t(item.is_new ? "本版本新增/状态变更" : "从父版继承")} · {discoveryKindText(item.discovery_kind)}</small></article>;
    }) : <p>{<Tx text={"这个版本没有保存合规证据来源。"} />}</p>}</div>
  </section>;
}

function explicitSourceKeys(report: Record<string, unknown> | null): Set<string> {
  const selection = report?.automatic_selection;
  if (typeof selection !== "object" || selection === null) return new Set();
  const refs = (selection as { explicit_source_refs?: unknown }).explicit_source_refs;
  if (!Array.isArray(refs)) return new Set();
  return new Set(refs.flatMap((ref) => {
    if (typeof ref !== "object" || ref === null) return [];
    const value = ref as { source_type?: unknown; source_id?: unknown };
    return typeof value.source_type === "string" && typeof value.source_id === "string"
      ? [`${value.source_type}:${value.source_id}`]
      : [];
  }));
}

function eventIdentity(item: Record<string, unknown>) {
  return String(item.event_version_id ?? item.id ?? `${item.source_type}:${item.source_id}`);
}

function sourceIdentity(item: Record<string, unknown>) {
  return `${String(item.source_type ?? "unknown")}:${String(item.source_id ?? eventIdentity(item))}`;
}

function shortHash(value: unknown) {
  const text = String(value ?? "—");
  return text.length > 14 ? `${text.slice(0, 12)}…` : text;
}

function marketSummary(manifest: Record<string, unknown>) {
  return [manifest.price_input_sha256, manifest.market_cutoff_at, manifest.latest_completed_session].map(String).join("|");
}

function coverageText(value: unknown) {
  if (value === true) return translatePhrase("覆盖不完整");
  if (value === false) return translatePhrase("覆盖状态已记录");
  return translatePhrase("覆盖状态未知");
}

function researchStatusText(value: unknown) {
  switch (value) {
    case "ready":
    case "succeeded": return translatePhrase("研究已就绪");
    case "failed":
    case "failed_before_run": return translatePhrase("研究失败");
    case "not_run": return translatePhrase("未运行研究");
    case "no_eligible_frozen_sources": return translatePhrase("没有合规保存来源");
    default: return translatePhrase("研究状态未记录");
  }
}

function triggerTypeText(value: unknown) {
  if (value === "manual_revision") return translatePhrase("人工发起修订");
  if (value === "automatic_monitor") return translatePhrase("监控发现材料");
  if (value === "new_forecast") return translatePhrase("新建预测");
  return translatePhrase("预测更新");
}

function discoveryKindText(value: unknown) {
  if (value === "official_scan") return translatePhrase("官方资料扫描发现");
  if (value === "manual_selection") return translatePhrase("人工选择");
  if (value === "uploaded") return translatePhrase("上传材料");
  return translatePhrase("来源记录");
}
