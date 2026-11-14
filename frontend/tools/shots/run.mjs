// Screenshot entry.
//   node run.mjs --dist <build dir> --out <dir> [--pages a,b] [--widths 390,1440] [--themes light,dark] [--locale zh-CN] [--strict]
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { parseArgs, csv } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";
import { summarizeUnmatched } from "./mock-api.mjs";
import { PAGES, waitReady } from "./pages.mjs";

const { flags } = parseArgs(process.argv.slice(2), { booleans: ["strict"] });
if (!flags.dist || !flags.out) { console.error("usage: node run.mjs --dist <dir> --out <dir> [--pages a,b] [--widths 390,1440] [--themes light,dark] [--locale zh-CN] [--strict]"); process.exit(2); }
const widths = csv(flags.widths, ["390", "1440"]).map(Number);
const themes = csv(flags.themes, ["light", "dark"]);
const locale = typeof flags.locale === "string" ? flags.locale : "zh-CN";
const wanted = csv(flags.pages, null);
const pages = wanted ? PAGES.filter((page) => wanted.includes(page.name)) : PAGES;
if (wanted) for (const name of wanted) if (!PAGES.some((page) => page.name === name)) { console.error(`unknown page: ${name}`); process.exit(2); }

await mkdir(flags.out, { recursive: true });
const server = await startServer(flags.dist);
const browser = await launch();
const unmatched = [];
const report = { dist: path.resolve(flags.dist), locale, widths, themes, shots: [], unmatched: [] };
let failures = 0;

for (const page of pages) {
  for (const theme of themes) {
    for (const width of widths) {
      const label = page.name;
      const file = `${page.name}.${theme}.${width}.png`;
      const view = await newView(browser, { width, theme, locale, identity: page.identity ?? "personal", label, unmatched });
      const entry = { file, page: page.name, theme, width, ok: true, consoleErrors: [], pageErrors: [] };
      try {
        await view.page.goto(`${server.url}${page.hash ?? ""}`, { waitUntil: "load" });
        await waitReady(view.page, page);
        await settle(view.page);
        if (page.before) { await page.before(view.page, { width, mock: view.mock }); await settle(view.page, { pinTranscript: false }); }
        // A page may name one element to photograph (the sample cards of the bots: one picture per bot) instead of the whole page.
        if (page.element) await view.page.locator(page.element).screenshot({ path: path.join(flags.out, file), animations: "disabled", caret: "hide" });
        else await view.page.screenshot({ path: path.join(flags.out, file), fullPage: true, animations: "disabled", caret: "hide" });
      } catch (error) {
        entry.ok = false; entry.error = String(error?.message ?? error).split("\n")[0]; failures += 1;
        await view.page.screenshot({ path: path.join(flags.out, file.replace(/\.png$/, ".FAILED.png")), fullPage: true }).catch(() => {});
      }
      entry.consoleErrors = view.problems.console; entry.pageErrors = view.problems.pageErrors;
      report.shots.push(entry);
      await view.close();
    }
  }
}
await browser.close(); await server.close();

report.unmatched = summarizeUnmatched(unmatched);
await writeFile(path.join(flags.out, "report.json"), `${JSON.stringify(report, null, 2)}\n`);

// Summary table
const pad = (value, size) => String(value).padEnd(size);
console.log(`\n${pad("page", 18)}${pad("theme", 7)}${pad("w", 6)}${pad("status", 8)}${pad("console.error", 15)}pageerror`);
for (const shot of report.shots) console.log(`${pad(shot.page, 18)}${pad(shot.theme, 7)}${pad(shot.width, 6)}${pad(shot.ok ? "ok" : "FAILED", 8)}${pad(shot.consoleErrors.length, 15)}${shot.pageErrors.length}${shot.error ? `   ${shot.error}` : ""}`);
console.log(`\nshots: ${report.shots.length}, failed: ${failures}, pages with console.error: ${new Set(report.shots.filter((s) => s.consoleErrors.length).map((s) => s.page)).size}, with pageerror: ${new Set(report.shots.filter((s) => s.pageErrors.length).map((s) => s.page)).size}`);
if (report.unmatched.length) { console.log(`\nunmatched API requests (${report.unmatched.length}):`); for (const item of report.unmatched) console.log(`  ${item.request}   <- ${item.pages.join(", ")}`); }
else console.log("\nunmatched API requests: none");
let code = failures ? 1 : 0;
if (flags.strict && report.unmatched.length) code = 1;
process.exit(code);
