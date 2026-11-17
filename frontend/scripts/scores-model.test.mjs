import assert from "node:assert/strict";
import test from "node:test";
import { cohortAverages, cohortGroups, cohortView, compareBars, fixed3, mean, modelStatusPhrase } from "../src/app/research/scores/scores-model.mjs";

const evaluation = (brier, logLoss, status = "succeeded") => ({ status, brier_score: brier, log_loss: logLoss });
const version = (latest) => ({ latest_evaluation: latest });
const summary = { version: "naive-vol-v1", paired_root_count: 6, baseline_unavailable_root_count: 1, model_mean_brier: 0.6, baseline_mean_brier: 0.8, model_mean_log_loss: 1.0, baseline_mean_log_loss: 0.9 };
const cohort = (extra = {}) => ({ time_mode: "observed", model_status: "experimental_llm", provider: "p", actual_model: "m", question_version: "q", status: "available", sample: { root_denominator: 34, labelled_root_count: 32, scored_root_count: 31, unscored_root_count: 3 },
  naive_baseline_summary: summary, roots: [{ versions: [version(evaluation(0.5, 1)), version(evaluation(0.7, 2)), version(evaluation(0.1, 0.1, "failed")), version(null)] }, { versions: [version(evaluation(null, null))] }], ...extra });

test("the average is over the versions whose latest evaluation succeeded, and only the numbers among them", () => {
  assert.deepEqual(cohortAverages(cohort()), { brier: 0.6, logLoss: 1.5 });
  assert.deepEqual(cohortAverages(cohort({ roots: [] })), { brier: null, logLoss: null });
  assert.equal(mean([]), null);
  assert.equal(mean([1, undefined, null, 2]), 1.5);
  assert.equal(fixed3(0.57149), "0.571");
  assert.equal(fixed3(null), null);
});

test("below the floor the card has no average and no comparison, whatever the cohort holds", () => {
  for (const status of ["pending", "insufficient_samples"]) {
    const view = cohortView(cohort({ status }), 30);
    assert.equal(view.available, false);
    assert.equal(view.brier, null);
    assert.equal(view.logLoss, null);
    assert.equal(view.comparison, null);
    assert.equal(view.floor, 30);
  }
});

test("at the floor the card has the averages (three places) and the baseline comparison from scoreCard", () => {
  const view = cohortView(cohort(), 30);
  assert.equal(view.available, true);
  assert.equal(view.brier, "0.600");
  assert.equal(view.logLoss, "1.500");
  assert.deepEqual(view.comparison.brier, { model: 0.6, baseline: 0.8, bars: { model: 75, baseline: 100 } });
  assert.deepEqual(view.comparison.logLoss.bars, { model: 100, baseline: 90 });
  assert.equal(view.comparison.pairedRootCount, 6);
  assert.equal(view.comparison.baselineUnavailableRootCount, 1);
  assert.equal(cohortView(cohort({ naive_baseline_summary: undefined }), 30).comparison, null);
});

test("the review rule's breach banner comes only from the API's state", () => {
  assert.equal(cohortView(cohort({ review_rule: { state: "breached" } }), 30).banner !== null, true);
  assert.equal(cohortView(cohort({ review_rule: { state: "passed" } }), 30).banner, null);
});

test("two bars start at zero and are in the numbers' real ratio", () => {
  assert.deepEqual(compareBars(0.5, 1), { model: 50, baseline: 100 });
  assert.deepEqual(compareBars(0, 0), { model: 0, baseline: 0 });
  assert.equal(compareBars(null, 1), null);
});

test("the forecast model's own cohorts and the earlier records are two groups, and an empty group is left out", () => {
  const llm = cohort();
  const jev = cohort({ model_status: "experimental_jev" });
  const control = cohort({ control: true });
  assert.deepEqual(cohortGroups([llm, jev, control]).map((g) => [g.key, g.items.length]), [["llm", 1], ["earlier", 2]]);
  assert.deepEqual(cohortGroups([llm]).map((g) => g.key), ["llm"]);
  assert.deepEqual(cohortGroups([]), []);
  assert.equal(modelStatusPhrase("experimental_llm"), "推理模型实验预测");
  assert.equal(modelStatusPhrase("nope"), "模型状态未记录");
});
