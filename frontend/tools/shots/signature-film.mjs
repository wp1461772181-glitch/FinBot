// The evidence film of the line's signature (A3), a stand-in for a screen recording: for each of the seven traces of thinking six frames of one loop, for
// each of the five carets four frames of one blink, for the closing line (done / partial / failed) five frames of the sweep, in contact sheets.  The frames
// are exact, not recorded: the sample page's row runs the real CSS; here every animation of the element is paused and put at a chosen time
// (`Animation.currentTime`), and the element is photographed.  Usage:
//   node signature-film.mjs --dist <build dir> --out <dir> [--themes light,dark]
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { parseArgs, csv } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";

const { flags } = parseArgs(process.argv.slice(2));
if (!flags.dist || !flags.out) { console.error("usage: node signature-film.mjs --dist <dir> --out <dir> [--themes light,dark]"); process.exit(2); }
const themes = csv(flags.themes, ["light"]);
const TRACES = ["candles", "streaks", "steps", "arc", "lines", "drift", "orbit"], CARETS = ["bar", "slant", "underline", "hairline", "bar-block"];
const SWEEP_MS = [0, 110, 220, 320, 520]; // the stroke at its start, a third, two thirds, full, then the fade done

await mkdir(flags.out, { recursive: true });
const server = await startServer(flags.dist);
const browser = await launch();
const unmatched = [];
const report = [];

/** Pause every animation under `selector` and put them all at `time` ms; the elements keep their own delays. */
const seek = (page, selector, time) => page.evaluate(([sel, at]) => {
  const root = document.querySelector(sel);
  for (const a of root.getAnimations({ subtree: true })) { a.pause(); a.currentTime = at; }
}, [selector, time]);
/** The longest single loop among an element's animations (ms), the period the frames divide. */
const cycleOf = (page, selector) => page.evaluate((sel) => Math.max(...document.querySelector(sel).getAnimations({ subtree: true }).map((a) => a.effect.getTiming().duration)), selector);

for (const theme of themes) {
  const view = await newView(browser, { width: 1440, theme, label: "signature-film", unmatched, motion: true });
  const { page } = view;
  await page.goto(`${server.url}#/dev/kit/bots`, { waitUntil: "load" });
  await page.waitForSelector("[data-testid=signature-row]");
  await settle(page);
  await page.locator("[data-testid=signature-row]").scrollIntoViewIfNeeded();
  const sheets = { traces: [], carets: [], lines: [] };
  const grab = async (selector, clipTarget, pad) => {
    const box = await page.locator(clipTarget).boundingBox();
    const png = await page.screenshot({ clip: { x: box.x - pad, y: box.y - pad, width: box.width + 2 * pad, height: box.height + 2 * pad } });
    return `data:image/png;base64,${png.toString("base64")}`;
  };
  for (const trace of TRACES) {
    const selector = `[data-testid=trace-${trace}]`, cycle = await cycleOf(page, selector), frames = [];
    for (let k = 0; k < 6; k += 1) { await seek(page, selector, (cycle * k) / 6); frames.push({ at: Math.round((cycle * k) / 6), src: await grab(selector, `${selector} .think-trace`, 3) }); }
    sheets.traces.push({ label: `${trace} · loop ${(cycle / 1000).toFixed(2)} s`, frames, scale: 7 });
    report.push({ theme, kind: "trace", name: trace, cycleMs: Math.round(cycle), frames: frames.map((f) => f.at) });
  }
  for (const caret of CARETS) {
    const selector = `[data-testid=caret-${caret}]`, cycle = await cycleOf(page, selector), frames = [];
    for (let k = 0; k < 4; k += 1) { const at = cycle * (0.08 + 0.25 * k); await seek(page, selector, at); frames.push({ at: Math.round(at), src: await grab(selector, `${selector} .chat-prose p`, 4) }); }
    sheets.carets.push({ label: `${caret} · blink ${(cycle / 1000).toFixed(2)} s`, frames, scale: 2 });
    report.push({ theme, kind: "caret", name: caret, cycleMs: Math.round(cycle), frames: frames.map((f) => f.at) });
  }
  for (const state of ["done", "partial", "failed"]) {
    const selector = `[data-testid=line-${state}]`, frames = [];
    for (const at of SWEEP_MS) { await seek(page, selector, at); frames.push({ at, src: await grab(selector, `${selector} [data-testid=done-line]`, 6) }); }
    sheets.lines.push({ label: state, frames, scale: 1 });
    report.push({ theme, kind: "line", name: state, frames: SWEEP_MS });
  }
  const dark = theme === "dark";
  const sheet = await browser.newPage({ viewport: { width: 1500, height: 600 } });
  for (const [kind, rows] of Object.entries(sheets)) {
    const html = `<style>body{margin:12px;background:${dark ? "#101010" : "#f4f3ef"};font:12px sans-serif;color:${dark ? "#ddd" : "#222"}}h2{margin:4px 0 8px}.row{display:flex;gap:8px;align-items:flex-end;margin-bottom:14px;flex-wrap:wrap}figure{margin:0;text-align:center}img{display:block;image-rendering:pixelated;border:1px solid ${dark ? "#333" : "#d8d6cf"}}figcaption{margin-top:3px;color:${dark ? "#aaa" : "#666"}}.name{width:200px;text-align:right;align-self:center;font-weight:600}</style>`
      + `<h2>Line signature · ${kind} (${theme})</h2>` + rows.map((r) => `<div class="row"><div class="name">${r.label}</div>${r.frames.map((f) => `<figure><img src="${f.src}" style="zoom:${r.scale}"><figcaption>${f.at} ms</figcaption></figure>`).join("")}</div>`).join("");
    await sheet.setContent(html);
    const file = `signature-film-${kind}${dark ? ".dark" : ""}.png`;
    await sheet.screenshot({ path: path.join(flags.out, file), fullPage: true });
    console.log(`wrote ${file}`);
  }
  await sheet.close();
  await view.close();
}
await writeFile(path.join(flags.out, "signature-film.json"), `${JSON.stringify(report, null, 2)}\n`);
await browser.close(); await server.close();
