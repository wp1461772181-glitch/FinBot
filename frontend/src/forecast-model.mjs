// Which model gave a forecast, and what the page says about it.  Pure: every value is a zh-CN phrase key (the
// component translates it with t()) or a value taken from the saved version.  Jev wording exists only for
// versions Jev itself made (marked 早期版本) and for the legacy branches of job errors.

export const NOT_RECORDED = "未记录";

const DECISION_STATUSES = new Set(["experimental_jev", "experimental_llm"]);

/** True when a version of this status carries `decision_probabilities` the page may show. */
export function hasDecisionProbabilities(status) {
  return DECISION_STATUSES.has(status);
}

function text(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/**
 * Copy for every spot that used to assume Jev.  `model` and `provider` come from the saved version and read
 * 未记录 when the version did not record them; they are never guessed.
 */
export function forecastCopy({ model_status, provider, actual_model, calibrated } = {}) {
  const base = { model: text(actual_model) ?? NOT_RECORDED, provider: text(provider) ?? NOT_RECORDED };
  if (model_status === "experimental_llm") {
    return {
      ...base,
      statusName: "推理模型实验判断（尚未校准）",
      statusNote: "由设置中的预测模型给出的实验概率，未经校准",
      stripLabel: "预测模型实验性概率 · 未校准",
      summaryNoteBefore: "由",
      summaryNoteAfter: "根据下方研究简报给出。未经校准，仅供参考。",
      timelineStripLabel: "实验性概率 · 未校准",
      evalLabel: "到期评估 · 同一模型组",
      evalAria: "所选预测的分组到期评估",
      evalNoMatchBody: "当前评估数据没有与此版本的时间模式、服务方、实际模型和问题版本完全匹配的分组；不会用混合分组代替。",
      evalScoreLabel: "实验性概率评分（模型未校准）：",
      briefAria: "实验性概率",
      briefTitle: "三分类实验性概率",
      briefNote: "以下是该模型对固定目标的实验性输出，不代表已验证概率。",
      briefBadge: "未校准",
      briefKickerProvider: base.provider,
      briefKickerModel: base.model,
      noProbabilityNote: "该版本只有研究简报，没有数值概率；页面不会回填旧版概率。",
      earlier: false,
    };
  }
  if (model_status === "experimental_jev") {
    return {
      ...base,
      statusName: "Jev 实验判断（早期版本，尚未校准）",
      statusNote: calibrated ? "Jev 输出已通过本地时间外校准；原始值可展开查看" : "当前使用 Jev 原始概率；本地校准器仍在积累到期样本",
      stripLabel: calibrated ? "Jev 经本地校准的实验性概率" : "Jev 原始实验性概率 · 未校准",
      summaryNoteBefore: "",
      summaryNoteAfter: calibrated
        ? "本地校准器只调整三类概率分布；Jev 原始输出保存在下方，模型和目标版本均有记录。"
        : "由 Jev 根据下方同一份 DeepSeek 研究简报输出。当前尚无通过时间外验证的本地校准器，因此显示原始概率。",
      timelineStripLabel: calibrated ? "Jev + 本地校准" : "Jev 原始实验性概率",
      evalLabel: "Jev 到期评估 · 同一模型组",
      evalAria: "所选 Jev 预测的分组到期评估",
      evalNoMatchBody: "当前评估数据没有与此版本的时间模式、Jev 服务方、实际模型和问题版本完全匹配的 cohort；不会使用混合旧分组代替。",
      evalScoreLabel: "Jev 实验性判断评分（模型未校准）：",
      briefAria: "Jev 实验性概率",
      briefTitle: calibrated ? "Jev 判断 · 本地校准" : "Jev 原始三分类判断",
      briefNote: calibrated
        ? "主结果经过本地校准器调整；原始 Jev 输出在下方保留以便比较。校准器不会更新 Jev 的内部参数。"
        : "以下是 Jev 对固定目标合同的实验性原始输出，不代表已验证概率。DeepSeek 只分析单份材料；系统复用这些已保存的分析并在本地汇总简报。",
      briefBadge: calibrated ? "时间外验证通过" : "未校准",
      briefKickerProvider: "OpenRouter",
      briefKickerModel: "Jev（早期版本）",
      noProbabilityNote: "该版本为仅研究模式，没有保存 Jev 数值判断；页面不会回填旧版概率。",
      earlier: true,
    };
  }
  const researchOnly = model_status === "research_only";
  const names = {
    experimental_joint: "联合研究模型",
    baseline_only: "行情基线模型",
    research_only: "研究结果（未输出概率）",
  };
  return {
    ...base,
    statusName: names[model_status] ?? "当前模型尚未验证",
    statusNote: researchOnly ? "当前只提供材料研究简报，没有数值概率" : "请将模型结果视为研究信息",
    stripLabel: "实验性概率 · 未校准",
    summaryNoteBefore: "",
    summaryNoteAfter: "",
    timelineStripLabel: "实验性概率 · 未校准",
    evalLabel: "到期评估",
    evalAria: "所选预测的到期评估",
    evalNoMatchBody: "当前评估数据没有与此版本完全匹配的分组；不会用混合分组代替。",
    evalScoreLabel: "实验性概率评分（模型未校准）：",
    briefAria: "实验性概率",
    briefTitle: "三分类实验性概率",
    briefNote: "以下是模型对固定目标的实验性输出，不代表已验证概率。",
    briefBadge: "未校准",
    briefKickerProvider: base.provider,
    briefKickerModel: base.model,
    noProbabilityNote: researchOnly
      ? "本版没有数值预测，研究简报只用于材料研究；页面不会回填旧版概率。"
      : "当前版本没有可显示的数值判断。",
    earlier: model_status === "experimental_joint" || model_status === "baseline_only",
  };
}

const JOB_FAILURES = {
  // The current pipeline.
  forecast_model_not_configured: "还没有可用的预测模型。请在设置中添加模型后重试。",
  forecast_model_not_found: "找不到所选的预测模型。请在设置中重新选择。",
  forecast_model_key_missing: "预测模型缺少密钥。请在设置中补上后重试。",
  forecast_provider_error: "预测模型暂时无法响应，可稍后重试。",
  forecast_invalid_response: "预测模型的回答无法解析，未发布预测。可重新创建任务。",
  forecast_invalid_probabilities: "预测模型给出的概率不合规（缺项、越界或总和不为 1），未发布预测。",
  forecast_invalid_brief: "研究简报无法提交给预测模型，未发布预测。",
  forecast_model_error: "预测模型调用失败，未发布预测，可稍后重试。",
  // Research brief.
  research_brief_failed: "研究简报构建失败，请查看服务日志后重试。",
  research_brief_provider_error: "研究简报服务暂不可用，可稍后重新创建任务。",
  research_brief_invalid_model_output: "研究简报的格式或引用校验未通过，可重新创建任务。",
  research_brief_invalid_background_reference: "模型把新材料当成背景材料引用，未通过来源分类校验；请重新创建预测。",
  research_brief_provider_required: "当前没有可用的研究简报模型配置，无法生成简报。",
  research_brief_invalid_brief_output: "简报没有通过结构校验，未发布预测。",
  // Legacy Jev codes: kept so old job rows still explain themselves.
  jev_missing_api_key: "早期 Jev 流程：缺少服务配置，未生成概率。",
  jev_authorization_or_billing_error: "早期 Jev 流程：服务授权或账单需要处理。",
  jev_upstream_unavailable: "早期 Jev 流程：服务暂不可用。",
  jev_transport_error: "早期 Jev 流程：连接服务失败。",
  // Market data.
  market_refresh_failed: "行情刷新失败，可稍后重试。",
  no_completed_market_session: "没有可用的已完成交易日行情。",
  insufficient_observed_market_history: "可观察行情不足，暂时无法建立预测输入。",
};

/**
 * The sentence (a zh-CN phrase key) for a job's failure code, or null when the code has no sentence and the
 * caller should fall back to its generic text.  A `forecast_*` code never falls through to the raw code.
 */
export function jobFailurePhrase(code) {
  if (typeof code !== "string" || !code) return "任务没有返回可识别的失败原因。";
  if (Object.hasOwn(JOB_FAILURES, code)) return JOB_FAILURES[code];
  if (code.startsWith("research_brief_")) return "研究简报未通过处理或引用校验，未发布预测。";
  if (code.startsWith("forecast_")) return "预测模型未完成判断，未发布预测。";
  if (code.startsWith("jev_")) return "早期 Jev 流程未完成，未发布概率。";
  return null;
}

// ---------------------------------------------------------------------------------------------------------
// Version header (design §3.1 and §3.2).  `versionHeader(detail)` reads one saved version and returns the rows
// the header shows, never collapsed.  A row is `{ id, label, items }`; an item is `{ t }` (a zh-CN phrase key
// the component translates), `{ v }` (a value taken from the version, shown as is) or `{ time }` (an ISO time
// the component formats).  The 模型来源 (binding) row is added in a later batch.
// ---------------------------------------------------------------------------------------------------------

function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function percent(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : NOT_RECORDED;
}

/** Provider and models recorded on a version, normalised (null when not recorded). */
export function recordedModel(detail) {
  const provider = record(record(detail?.model_manifest).decision_provider);
  return { provider: text(provider.provider), actual_model: text(provider.actual_model), requested_model: text(provider.requested_model) };
}

/** True when `current` was decided by a different provider or actual model than `parent`.  No parent: false. */
export function modelChanged(current, parent) {
  if (!current || !parent) return false;
  const a = recordedModel(current);
  const b = recordedModel(parent);
  return a.provider !== b.provider || a.actual_model !== b.actual_model;
}

function isInsufficient(detail) {
  return record(record(detail?.research_brief).input_quality).status === "insufficient"
    || record(detail?.feature_snapshot).research_brief_input_quality === "insufficient"
    || record(detail?.research_report).research_conclusions_status === "insufficient";
}

function timeMode(detail) {
  return record(detail?.model_manifest).time_mode ?? record(detail?.research_report).time_mode ?? null;
}

function modelItems(detail, copy) {
  const status = detail?.model_status;
  const { provider, actual_model, requested_model } = recordedModel(detail);
  if (status === "research_only") {
    if (isInsufficient(detail)) return [{ t: "仅研究 · 本版没有输出概率：证据不足，模型未作判断" }];
    if (record(detail?.model_manifest).decision_mode === "research_only") return [{ t: "仅研究 · 当前配置不生成概率" }];
    return [{ t: copy.statusName }];
  }
  if (status === "experimental_llm" || status === "experimental_jev") {
    const items = [{ v: actual_model ?? NOT_RECORDED }];
    if (provider) items.push({ v: ` · ${provider}` });
    if (status === "experimental_jev") items.push({ t: "（早期版本）" });
    if (actual_model && requested_model && requested_model !== actual_model) {
      items.push({ v: " · " }, { t: "请求" }, { v: ` ${requested_model}` }, { t: "，实际返回" }, { v: ` ${actual_model}` });
    }
    return items;
  }
  // Older joint or baseline versions keep their own names, marked 早期版本; an unknown status reads 未记录.
  if (status === "experimental_joint" || status === "baseline_only") return [{ t: copy.statusName }, { t: "（早期版本）" }];
  return [{ v: NOT_RECORDED }];
}

/** Rows of the version header for one saved version (the version as the API returns it). */
export function versionHeader(detail) {
  const status = detail?.model_status;
  const manifest = record(detail?.model_manifest);
  const decision = record(manifest.decision_provider);
  const calibrated = status === "experimental_jev" && record(manifest.local_calibration).status === "active";
  const copy = forecastCopy({ model_status: status, provider: decision.provider, actual_model: decision.actual_model, calibrated });
  const rows = [];

  rows.push({ id: "model", label: "决策模型", items: modelItems(detail, copy) });
  rows.push({ id: "method", label: "决策方式", items: [{ t: status === "experimental_llm" ? "推理模型" : copy.statusName }] });

  const contract = record(detail?.target_contract);
  const horizon = typeof contract.horizon_sessions === "number" ? String(contract.horizon_sessions) : null;
  const threshold = typeof contract.threshold === "number" ? `${Math.round(contract.threshold * 10000) / 100}%` : null;
  const question = horizon && threshold
    ? [{ v: horizon }, { t: "个交易日收盘相对锚点 ±" }, { v: threshold }]
    : [{ v: NOT_RECORDED }];
  if (hasDecisionProbabilities(status)) question.push({ v: ` · ${text(decision.question_version) ?? NOT_RECORDED}` });
  rows.push({ id: "question", label: "问题", items: question });

  rows.push({ id: "calibration", label: "校准状态", items: [{ t: calibrated ? "已通过本地时间外校准" : "未校准" }] });

  const probabilities = hasDecisionProbabilities(status) ? record(detail?.decision_probabilities) : null;
  if (probabilities && Object.keys(probabilities).length > 0) {
    rows.push({
      id: "probabilities",
      label: "概率",
      items: [
        { t: "下跌 <−2%" }, { v: ` ${percent(probabilities.bearish)} · ` },
        { t: "持平 ±2%" }, { v: ` ${percent(probabilities.neutral)} · ` },
        { t: "上涨 >+2%" }, { v: ` ${percent(probabilities.bullish)}` },
      ],
    });
  }

  rows.push({
    id: "times",
    label: "时间",
    items: [
      { t: "决策" }, { v: " " }, { time: detail?.decision_at ?? null }, { v: " · " },
      { t: "行情截止" }, { v: " " }, { time: detail?.market_cutoff_at ?? null }, { v: " · " },
      { t: "目标日" }, { v: ` ${text(contract.target_end_date) ?? NOT_RECORDED} · ` },
      { t: "第" }, { v: ` ${detail?.version_no ?? "—"} ` }, { t: "版" },
    ],
  });

  if (timeMode(detail) === "historical_research") rows.push({ id: "time_mode", label: "时间模式", items: [{ t: "历史回放" }] });
  return rows;
}
