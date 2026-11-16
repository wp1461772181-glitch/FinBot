import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

// Design 7.3, P6.2 acceptance 1: the two lanes of the forecast home are two problems with two kinds of data, so each has its own row component.  They may
// share small parts (the probability bar, the status badge: those are imported from components/), never a row, and one never imports the other.
const DIR = new URL("../src/app/research/forecasts/", import.meta.url).pathname;
const read = (name) => readFileSync(join(DIR, name), "utf8");
// What the file does, without its comments (a comment may say what the row does not do).
const code = (name) => read(name).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const localImports = (source) => [...source.matchAll(/from\s+["'](\.\/[^"']+)["']/g)].map((match) => match[1].replace(/^\.\//, "").replace(/\.(tsx?|mjs)$/, ""));

test("the formal row and the judgment row are two files that import neither each other nor a common local module", () => {
  const formal = localImports(read("FormalForecastRow.tsx"));
  const judgment = localImports(read("JudgmentRow.tsx"));
  assert.ok(!formal.includes("JudgmentRow"), "FormalForecastRow imports JudgmentRow");
  assert.ok(!judgment.includes("FormalForecastRow"), "JudgmentRow imports FormalForecastRow");
  const shared = formal.filter((name) => judgment.includes(name));
  assert.deepEqual(shared, [], `the two rows share a local module: ${shared.join(", ")}`);
});

test("no third file in the folder is a generic row that carries both lanes' slots", () => {
  const rows = readdirSync(DIR).filter((name) => /\.tsx$/.test(name)).filter((name) => /data-slot="(formal|judgment)-row"/.test(read(name)));
  assert.deepEqual(rows.sort(), ["FormalForecastRow.tsx", "JudgmentRow.tsx"]);
  assert.match(read("FormalForecastRow.tsx"), /data-slot="formal-row"/);
  assert.match(read("JudgmentRow.tsx"), /data-slot="judgment-row"/);
  assert.doesNotMatch(read("FormalForecastRow.tsx"), /judgment-row/);
  assert.doesNotMatch(read("JudgmentRow.tsx"), /formal-row/);
});

test("a judgment row cannot draw a probability bar and a formal row has no direction word", () => {
  assert.doesNotMatch(code("JudgmentRow.tsx"), /ProbabilityBar|probabilit/i);
  assert.doesNotMatch(code("FormalForecastRow.tsx"), /偏涨|偏跌|把握/);
});

test("the home page uses both rows, each in its own lane", () => {
  const home = read("ForecastHome.tsx");
  assert.match(home, /import \{ FormalForecastRow \} from "\.\/FormalForecastRow"/);
  assert.match(home, /import \{ JudgmentRow \} from "\.\/JudgmentRow"/);
});
