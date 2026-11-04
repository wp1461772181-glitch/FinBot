import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";

// "Jev" and "DeepSeek" may appear in the forecast path only where a record Jev made, or a legacy error code, needs
// them.  Anything else is copy that would tell the user a model ran when it did not.  The list starts generous
// (B1) and is tightened when the calibrator and its branches are removed (B5).
const SRC = new URL("../src/", import.meta.url).pathname;
const SKIP_DIRS = new Set(["locales"]);
const EXTENSIONS = /\.(tsx?|mjs|js|css)$/;

const ALLOWED = {
  Jev: new Set([
    "forecast-model.mjs",             // the experimental_jev branch and legacy jev_* error sentences
    "EvidenceCenter.tsx",             // version label for an old Jev version
    "HistoricalReplayWorkspace.tsx",  // modelLabel for an old Jev replay
    "App.tsx",                        // modelStatusLabel branch and the 早期版本 cohort note
    "V2ForecastWorkspace.tsx",        // calibrated-branch label (removed with the calibrator, B5)
    "ResearchBriefView.tsx",          // calibrated-branch label (removed with the calibrator, B5)
  ]),
  DeepSeek: new Set([
    "forecast-model.mjs",             // the Jev branch note that names the brief provider
    "AgentChatPanel.tsx",             // chat model selector, not the forecast path
    "model-profiles.mjs",             // provider catalogue
    "MaterialAnalysisDetail.tsx",     // single-material analysis, not the forecast path
  ]),
};

function sources(dir) {
  const found = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (!SKIP_DIRS.has(name)) found.push(...sources(path));
    } else if (EXTENSIONS.test(name)) {
      found.push(path);
    }
  }
  return found;
}

for (const word of Object.keys(ALLOWED)) {
  test(`"${word}" appears in frontend/src only in allowlisted files`, () => {
    const offenders = sources(SRC)
      .filter((path) => readFileSync(path, "utf8").includes(word))
      .map((path) => relative(SRC, path))
      .filter((file) => !ALLOWED[word].has(file.split("/").pop()));
    assert.deepEqual(offenders, [], `${word} found outside the allowlist`);
  });
}

test("CSS carries no Jev-named brief classes", () => {
  for (const path of sources(SRC).filter((file) => file.endsWith(".css"))) {
    assert.doesNotMatch(readFileSync(path, "utf8"), /brief-(raw-)?jev/, relative(SRC, path));
  }
});

test("an LLM-facing view never shows the removed learning panel", () => {
  for (const path of sources(SRC).filter((file) => /\.(tsx?|mjs)$/.test(file))) {
    const source = readFileSync(path, "utf8");
    assert.doesNotMatch(source, /JevLearningReadout|getJevLearningStatus|jev-learning\/status/, relative(SRC, path));
  }
});
