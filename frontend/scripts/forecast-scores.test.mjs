import assert from "node:assert/strict";
import test from "node:test";
import { BREACH_BANNER, scoreCard } from "../src/forecast-model.mjs";

const summary = { version: "naive-vol-v1", paired_root_count: 6, baseline_unavailable_root_count: 1, model_mean_brier: 0.61, baseline_mean_brier: 0.58, model_mean_log_loss: 1.02, baseline_mean_log_loss: 0.95 };

test("model-vs-baseline means are hidden below the available floor", () => {
  for (const status of ["pending", "insufficient_samples"]) {
    const card = scoreCard({ status, naive_baseline_summary: summary });
    assert.equal(card.showMeans, false);
    assert.equal(card.modelBrier, null);
    assert.equal(card.baselineBrier, null);
    assert.equal(card.modelLogLoss, null);
    assert.equal(card.baselineLogLoss, null);
  }
});

test("means are shown at available, on the paired roots", () => {
  const card = scoreCard({ status: "available", naive_baseline_summary: summary });
  assert.equal(card.showMeans, true);
  assert.equal(card.pairedRootCount, 6);
  assert.equal(card.baselineUnavailableRootCount, 1);
  assert.equal(card.modelBrier, 0.61);
  assert.equal(card.baselineBrier, 0.58);
  assert.equal(card.modelLogLoss, 1.02);
  assert.equal(card.baselineLogLoss, 0.95);
  assert.equal(card.bannerKey, null);
});

test("no paired roots, or no summary, shows nothing", () => {
  assert.equal(scoreCard({ status: "available", naive_baseline_summary: { ...summary, paired_root_count: 0, model_mean_brier: null } }).showMeans, false);
  assert.equal(scoreCard({ status: "available" }).showMeans, false);
  assert.equal(scoreCard(null).breached, false);
});

test("a breached review rule gives the banner key; collecting and passed do not", () => {
  const base = { status: "available", naive_baseline_summary: summary };
  const breached = scoreCard({ ...base, review_rule: { threshold: 30, paired_root_count: 30, state: "breached" } });
  assert.equal(breached.breached, true);
  assert.equal(breached.bannerKey, BREACH_BANNER);
  for (const state of ["collecting", "passed"]) {
    const card = scoreCard({ ...base, review_rule: { threshold: 30, paired_root_count: 30, state } });
    assert.equal(card.breached, false);
    assert.equal(card.bannerKey, null);
  }
});
