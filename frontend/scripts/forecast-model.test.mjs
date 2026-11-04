import assert from "node:assert/strict";
import test from "node:test";
import { forecastCopy, hasDecisionProbabilities, jobFailurePhrase, modelChanged, NOT_RECORDED, versionHeader } from "../src/forecast-model.mjs";

const LLM = { model_status: "experimental_llm", provider: "zhipu", actual_model: "glm-5.3-flash" };
const BANNED = /Jev|OpenRouter|DeepSeek/;

test("an LLM version never shows Jev, OpenRouter or DeepSeek wording", () => {
  const copy = forecastCopy(LLM);
  for (const [key, value] of Object.entries(copy)) {
    if (typeof value === "string") assert.doesNotMatch(value, BANNED, key);
  }
  assert.equal(copy.model, "glm-5.3-flash");
  assert.equal(copy.earlier, false);
  assert.doesNotMatch(copy.stripLabel, /校准[^未]/);
});

test("a Jev version names Jev and is marked as an earlier version", () => {
  const copy = forecastCopy({ model_status: "experimental_jev", provider: "openrouter", actual_model: "typesafe/jev-1.13" });
  const joined = Object.values(copy).filter((value) => typeof value === "string").join("\n");
  assert.match(joined, /Jev/);
  assert.match(copy.statusName, /早期版本/);
  assert.equal(copy.model, "typesafe/jev-1.13");
  assert.equal(copy.earlier, true);
});

test("a version with no recorded model reads 未记录, never Jev or a guess", () => {
  for (const status of ["experimental_llm", "experimental_jev"]) {
    for (const missing of [undefined, null, "", "   ", 7]) {
      const copy = forecastCopy({ model_status: status, provider: missing, actual_model: missing });
      assert.equal(copy.model, NOT_RECORDED);
      assert.equal(copy.provider, NOT_RECORDED);
    }
  }
  assert.equal(forecastCopy({ model_status: "experimental_llm" }).briefKickerModel, "未记录");
  assert.doesNotMatch(forecastCopy({ model_status: "experimental_llm" }).briefKickerModel, /Jev/);
  assert.equal(forecastCopy().model, "未记录");
});

test("research-only and older statuses get their own plain words", () => {
  assert.match(forecastCopy({ model_status: "research_only" }).noProbabilityNote, /没有数值预测/);
  assert.equal(forecastCopy({ model_status: "baseline_only" }).statusName, "行情基线模型");
  assert.equal(forecastCopy({ model_status: "something_new" }).statusName, "当前模型尚未验证");
});

const NEW_CODES = [
  "forecast_model_not_configured", "forecast_model_not_found", "forecast_model_key_missing", "forecast_provider_error",
  "forecast_invalid_response", "forecast_invalid_probabilities", "forecast_invalid_brief", "forecast_model_error",
];
const REPLACED = ["research_brief_provider_error", "research_brief_invalid_model_output", "research_brief_provider_required"];
const LEGACY = ["jev_missing_api_key", "jev_authorization_or_billing_error", "jev_upstream_unavailable", "jev_transport_error"];

test("every job error code and prefix gives a sentence, and no forecast_ result shows the raw code", () => {
  for (const code of [...NEW_CODES, ...REPLACED, ...LEGACY, "forecast_something_unlisted", "research_brief_other", "jev_other"]) {
    const phrase = jobFailurePhrase(code);
    assert.ok(phrase && phrase.length > 0, code);
    if (code.startsWith("forecast_")) assert.ok(!phrase.includes(code), code);
  }
  assert.equal(jobFailurePhrase("forecast_something_unlisted"), "预测模型未完成判断，未发布预测。");
  assert.equal(jobFailurePhrase("jev_other"), "早期 Jev 流程未完成，未发布概率。");
  assert.equal(jobFailurePhrase(null), "任务没有返回可识别的失败原因。");
  assert.equal(jobFailurePhrase("totally_unknown_code"), null);
});

test("replaced brief errors no longer name DeepSeek, and legacy Jev errors say they are the earlier flow", () => {
  for (const code of REPLACED) assert.doesNotMatch(jobFailurePhrase(code), /DeepSeek/);
  for (const code of LEGACY) assert.match(jobFailurePhrase(code), /早期 Jev 流程/);
});

// --- B2: version header ------------------------------------------------------------------------------------

const CONTRACT = { target_end_date: "2026-12-01", horizon_sessions: 20, threshold: 0.02 };
const PROBS = { bearish: 0.18, neutral: 0.3, bullish: 0.52 };

function version(overrides = {}) {
  return {
    model_status: "experimental_llm",
    model_manifest: {
      decision_mode: "llm",
      time_mode: "observed",
      decision_provider: { provider: "zhipu", requested_model: "glm-5.3-flash", actual_model: "glm-5.3-flash", question_version: "llm-direction-v1" },
      local_calibration: { status: "not_applied" },
    },
    target_contract: CONTRACT,
    decision_probabilities: PROBS,
    research_report: { time_mode: "observed" },
    feature_snapshot: {},
    decision_at: "2026-11-02T20:00:00Z",
    market_cutoff_at: "2026-11-02T21:00:00Z",
    version_no: 2,
    ...overrides,
  };
}

// Flatten a row to the text a reader sees; phrases are zh-CN keys, values are shown as is.
function flat(header, id) {
  const row = header.find((entry) => entry.id === id);
  if (!row) return null;
  return row.items.map((item) => ("t" in item ? item.t : "v" in item ? item.v : item.time ?? NOT_RECORDED)).join("");
}

function jevVersion(overrides = {}) {
  return version({
    model_status: "experimental_jev",
    model_manifest: {
      decision_mode: "jev",
      time_mode: "observed",
      decision_provider: { provider: "openrouter", requested_model: "typesafe/jev-1.13", actual_model: "typesafe/jev-1.13", question_version: "jev-direction-v1" },
      local_calibration: { status: "not_applied" },
    },
    version_no: 1,
    ...overrides,
  });
}

test("an LLM version's header carries every §3.1 row and no Jev wording", () => {
  const header = versionHeader(version());
  assert.deepEqual(header.map((row) => row.id), ["model", "method", "question", "calibration", "probabilities", "times"]);
  assert.equal(flat(header, "model"), "glm-5.3-flash · zhipu");
  assert.equal(flat(header, "method"), "推理模型");
  assert.equal(flat(header, "question"), "20个交易日收盘相对锚点 ±2% · llm-direction-v1");
  assert.equal(flat(header, "calibration"), "未校准");
  assert.equal(flat(header, "probabilities"), "下跌 <−2% 18% · 持平 ±2% 30% · 上涨 >+2% 52%");
  assert.match(flat(header, "times"), /目标日 2026-12-01 · 第 2 版/);
  assert.equal(header.some((row) => row.id === "time_mode"), false);
  assert.equal(header.some((row) => row.id === "binding"), false, "模型来源 waits for B6");
  assert.doesNotMatch(JSON.stringify(header), /Jev|OpenRouter|DeepSeek/);
});

test("a historical replay shows its time mode; an observed version does not", () => {
  const replay = versionHeader(version({ model_manifest: { ...version().model_manifest, time_mode: "historical_research" } }));
  assert.equal(flat(replay, "time_mode"), "历史回放");
});

test("an old Jev version names Jev's real model and is marked 早期版本", () => {
  const header = versionHeader(jevVersion());
  assert.equal(flat(header, "model"), "typesafe/jev-1.13 · openrouter（早期版本）");
  assert.match(flat(header, "method"), /Jev.*早期版本/);
});

test("requested differing from actual reads 请求 X，实际返回 Y; equal values add nothing", () => {
  const differs = version();
  differs.model_manifest.decision_provider = { ...differs.model_manifest.decision_provider, requested_model: "glm-5.3", actual_model: "glm-5.3-flash" };
  assert.match(flat(versionHeader(differs), "model"), /请求 glm-5\.3，实际返回 glm-5\.3-flash$/);
  assert.doesNotMatch(flat(versionHeader(version()), "model"), /请求/);
});

test("§3.2: a version with no recorded model reads 未记录, never Jev or a guess", () => {
  for (const manifest of [{}, { decision_provider: {} }, { decision_provider: { provider: "", actual_model: "  " } }]) {
    const header = versionHeader(version({ model_manifest: manifest }));
    assert.match(flat(header, "model"), /^未记录/);
    assert.doesNotMatch(flat(header, "model"), /Jev/);
  }
  assert.equal(flat(versionHeader(version({ model_status: "something_new", model_manifest: {}, decision_probabilities: null })), "model"), "未记录");
  assert.equal(flat(versionHeader(null), "model"), "未记录");
});

test("§3.2: evidence-insufficient research-only version says the model made no judgment", () => {
  const sentence = "仅研究 · 本版没有输出概率：证据不足，模型未作判断";
  for (const insufficient of [
    { research_brief: { input_quality: { status: "insufficient" } } },
    { feature_snapshot: { research_brief_input_quality: "insufficient" } },
    { research_report: { research_conclusions_status: "insufficient" } },
  ]) {
    const header = versionHeader(version({ model_status: "research_only", decision_probabilities: null, ...insufficient }));
    assert.equal(flat(header, "model"), sentence);
    assert.equal(header.some((row) => row.id === "probabilities"), false);
  }
});

test("§3.2: research-only deployment mode says the configuration produces no probabilities", () => {
  const header = versionHeader(version({ model_status: "research_only", decision_probabilities: null, model_manifest: { decision_mode: "research_only", time_mode: "observed" } }));
  assert.equal(flat(header, "model"), "仅研究 · 当前配置不生成概率");
});

test("§3.2: older joint and baseline versions keep their names, marked 早期版本", () => {
  assert.equal(flat(versionHeader(version({ model_status: "experimental_joint", model_manifest: {}, decision_probabilities: null })), "model"), "联合研究模型（早期版本）");
  assert.equal(flat(versionHeader(version({ model_status: "baseline_only", model_manifest: {}, decision_probabilities: null })), "model"), "行情基线模型（早期版本）");
});

test("the calibrator is retired: no version, even one carrying an old local_calibration, claims to be calibrated", () => {
  const old = jevVersion();
  old.model_manifest.local_calibration = { status: "active" };
  assert.equal(flat(versionHeader(old), "calibration"), "未校准");
  const llm = version();
  llm.model_manifest.local_calibration = { status: "active" };
  assert.equal(flat(versionHeader(llm), "calibration"), "未校准");
});

test("a Jev v1 and LLM v2 chain: each version shows its own model and modelChanged is true (review focus 1)", () => {
  const v1 = jevVersion();
  const v2 = version();
  assert.match(flat(versionHeader(v1), "model"), /^typesafe\/jev-1\.13/);
  assert.match(flat(versionHeader(v2), "model"), /^glm-5\.3-flash/);
  assert.equal(modelChanged(v2, v1), true);
  assert.equal(modelChanged(v1, v2), true);
});

test("modelChanged is false for the same provider and model, and for no parent", () => {
  assert.equal(modelChanged(version(), version({ version_no: 1 })), false);
  assert.equal(modelChanged(version(), null), false);
  assert.equal(modelChanged(null, version()), false);
  assert.equal(modelChanged(version({ model_manifest: {} }), version({ model_manifest: {} })), false);
  const other = version();
  other.model_manifest.decision_provider = { ...other.model_manifest.decision_provider, actual_model: "glm-5.4" };
  assert.equal(modelChanged(version(), other), true);
});

test("hasDecisionProbabilities is true only for the two decision statuses", () => {
  assert.equal(hasDecisionProbabilities("experimental_jev"), true);
  assert.equal(hasDecisionProbabilities("experimental_llm"), true);
  for (const other of ["research_only", "baseline_only", "experimental_joint", "unavailable", "", null, undefined]) {
    assert.equal(hasDecisionProbabilities(other), false);
  }
});
