// Accessibility pass (P9.1): every page name of pages.mjs, light and dark, opened as the screenshot run opens it, then axe-core over the document.
//   node axe.mjs --dist <build dir> --out <report.json> [--pages a,b] [--themes light,dark] [--width 1440]      (axe-core is a dev dependency of THIS package only)
// Reports the violations of impact `critical` and `serious`; the rest is counted.  The `color-contrast` rule is off: contrast is guarded by the token tests (scripts/theme-contrast.mjs),
// and axe cannot read it over gradients and the bot's painted faces.  Resumable: a page already in the output file is skipped.
import fs from "node:fs";
import { createRequire } from "node:module";
import { parseArgs, csv } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";
import { PAGES, waitReady } from "./pages.mjs";

const require = createRequire(import.meta.url);
const { flags } = parseArgs(process.argv.slice(2));
if (!flags.dist || !flags.out) { console.error("usage: node axe.mjs --dist <dir> --out <report.json> [--pages a,b] [--themes light,dark] [--width 1440]"); process.exit(2); }
const themes = csv(flags.themes, ["light", "dark"]);
const wanted = csv(flags.pages, null);
const pages = wanted ? PAGES.filter((page) => wanted.includes(page.name)) : PAGES;
const report = fs.existsSync(flags.out) ? JSON.parse(fs.readFileSync(flags.out, "utf8")) : { results: {}, rules: {} };
const axeSource = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const server = await startServer(flags.dist);
const browser = await launch();
const unmatched = [];
for (const page of pages) for (const theme of themes) {
  const width = page.widths ? page.widths[0] : Number(flags.width ?? 1440);
  const key = `${page.name}.${theme}.${width}`;
  if (report.results[key]) continue;
  const view = await newView(browser, { width, theme, identity: page.identity ?? "personal", label: page.name, unmatched, ...(typeof page.view === "function" ? page.view() : page.view ?? {}) });
  try {
    await view.page.goto(`${server.url}${page.hash ?? ""}`, { waitUntil: "load" });
    await waitReady(view.page, page);
    await settle(view.page);
    if (page.before) { await page.before(view.page, { width, mock: view.mock }); await settle(view.page, { pinTranscript: false }); }
    await view.page.evaluate(axeSource);
    const out = await view.page.evaluate(async () => {
      const result = await window.axe.run(document, { rules: { "color-contrast": { enabled: false } }, resultTypes: ["violations"] });
      return result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 5).map((n) => ({ target: n.target.join(" "), html: n.html.slice(0, 160) })), count: v.nodes.length }));
    });
    report.results[key] = out;
    for (const v of out) report.rules[v.id] = { impact: v.impact, help: v.help };
  } catch (error) { report.results[key] = [{ id: "RUN-ERROR", impact: "error", help: String(error?.message ?? error).split("\n")[0], nodes: [], count: 1 }]; }
  await view.close();
  fs.writeFileSync(flags.out, JSON.stringify(report));
}
await browser.close(); await server.close();
const severe = Object.entries(report.results).flatMap(([key, list]) => list.filter((v) => v.impact === "critical" || v.impact === "serious").map((v) => ({ key, ...v })));
const byRule = new Map(); for (const v of severe) { const e = byRule.get(v.id) ?? { rule: v.id, impact: v.impact, help: v.help, pages: [], nodes: 0 }; e.pages.push(v.key); e.nodes += v.count; byRule.set(v.id, e); }
console.log(`${Object.keys(report.results).length} views; critical/serious findings: ${severe.length}`);
for (const e of byRule.values()) console.log(`  ${e.impact} ${e.rule}: ${e.pages.length} views, ${e.nodes} nodes — ${e.help}`);
const errors = Object.entries(report.results).filter(([, list]) => list.some((v) => v.id === "RUN-ERROR")); if (errors.length) console.log(`  run errors: ${errors.map(([k]) => k).join(", ")}`);
