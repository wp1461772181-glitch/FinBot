import assert from "node:assert/strict";
import test from "node:test";
import { forecastCopy, hasDecisionProbabilities, jobFailurePhrase, NOT_RECORDED } from "../src/forecast-model.mjs";

const LLM = { model_status: "experimental_llm", provider: "zhipu", actual_model: "glm-5.3-flash", calibrated: false };
const BANNED = /Jev|OpenRouter|DeepSeek/;

test("an LLM version never shows Jev, OpenRouter or DeepSeek wording", () => {
  const copy = forecastCopy(LLM);
  for (const [key, value] of Object.entries(copy)) {
    if (typeof value === "string") assert.doesNotMatch(value, BANNED, key);
  }
  assert.equal(copy.model, "glm-5.3-flash");
  assert.equal(copy.earlier, false);
  // A requested calibration flag does not turn the LLM into a calibrated forecast.
  assert.doesNotMatch(forecastCopy({ ...LLM, calibrated: true }).stripLabel, /校准[^未]/);
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

test("hasDecisionProbabilities is true only for the two decision statuses", () => {
  assert.equal(hasDecisionProbabilities("experimental_jev"), true);
  assert.equal(hasDecisionProbabilities("experimental_llm"), true);
  for (const other of ["research_only", "baseline_only", "experimental_joint", "unavailable", "", null, undefined]) {
    assert.equal(hasDecisionProbabilities(other), false);
  }
});
