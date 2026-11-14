// The evidence film of the aura's four beats (A2): for each of the five bots, eight frames of a turn (collect x4, check x2, close x2) and four of a
// failed one, side by side in one picture, each with its moment, phase and unit count.  The frames are exact, not recorded: the sample page's
// `window.__auraFilm.frame(bot, T, ending)` runs the real director and tracker on explicit times up to T and draws the aura of that moment into a still
// body (the body is not part of what is filmed).  Usage:
//   node aura-film.mjs --dist <build dir> --out <dir> [--bots TeslaBot,NewsBot] [--themes light,dark] [--tier L|M]
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { parseArgs, csv } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";

const { flags } = parseArgs(process.argv.slice(2));
if (!flags.dist || !flags.out) { console.error("usage: node aura-film.mjs --dist <dir> --out <dir> [--bots a,b] [--themes light,dark] [--tier L|M]"); process.exit(2); }
const themes = csv(flags.themes, ["light"]);
const tier = flags.tier === "M" ? "M" : "L";
/** The moments (seconds into the scripted turn) of the strips: the turn starts at 0.2, tools return at 1.0 / 1.7 / 2.4, the check starts at 3.1, the end is at 4.4. */
const DONE = [[0.95, "collect"], [1.2, "collect"], [1.95, "collect"], [2.7, "collect"], [3.2, "check"], [3.35, "check"], [4.56, "close"], [5.0, "close"]];
const FAIL = [[4.5, "break"], [4.7, "break"], [5.1, "break"], [6.0, "break"]];
const CLIP = { w: 330, h: 250 };

await mkdir(flags.out, { recursive: true });
const server = await startServer(flags.dist);
const browser = await launch();
const unmatched = [];
const report = [];
let failures = 0;

for (const theme of themes) {
  const view = await newView(browser, { width: 1440, theme, label: "aura-film", unmatched });
  await view.page.goto(`${server.url}#/dev/kit/bots`, { waitUntil: "load" });
  await view.page.waitForSelector("[data-testid=bots-page]");
  await settle(view.page);
  await view.page.waitForFunction(() => Boolean(window.__auraFilm));
  const bots = csv(flags.bots, await view.page.evaluate(() => window.__auraFilm.bots));
  const sheet = await browser.newPage({ viewport: { width: 2800, height: 600 } });
  for (const bot of bots) {
    const strips = [];
    for (const [script, ending, label] of [[DONE, "done", "done"], [FAIL, "error", "failed"]]) {
      const frames = [];
      for (const [T, beat] of script) {
        const info = await view.page.evaluate(([name, at, end, size]) => window.__auraFilm.frame(name, at, end, size), [bot, T, ending, tier]);
        if (!info) { failures += 1; console.error(`no film frame for ${bot} at ${T}`); continue; }
        const avatar = view.page.locator(`[data-testid=film-${bot}] [data-slot=bot-avatar]`);
        await avatar.scrollIntoViewIfNeeded();
        const box = await avatar.boundingBox();
        const png = await view.page.screenshot({ clip: { x: box.x + box.width / 2 - CLIP.w / 2, y: box.y + box.height / 2 - CLIP.h / 2, width: CLIP.w, height: CLIP.h }, animations: "disabled" });
        frames.push({ T, beat, ...info, src: `data:image/png;base64,${png.toString("base64")}` });
      }
      strips.push({ label, frames });
      report.push({ bot, theme, tier, strip: label, frames: frames.map(({ src, ...rest }) => rest) });
    }
    const dark = theme === "dark";
    const html = `<style>body{margin:10px;background:${dark ? "#101010" : "#f4f3ef"};font:12px sans-serif;color:${dark ? "#ddd" : "#222"}}h2{margin:6px 0}.row{display:flex;gap:6px;margin-bottom:12px}figure{margin:0;border:1px solid ${dark ? "#333" : "#d8d6cf"};background:${dark ? "#1b1b1b" : "#fff"}}img{display:block}figcaption{padding:3px 6px;font-size:11px;white-space:nowrap}</style>`
      + strips.map(s => `<h2>${bot} · ${s.label === "done" ? "collect → check → close" : "break"} (${tier}, ${theme})</h2><div class="row">${s.frames.map(f => `<figure><img src="${f.src}" width="${CLIP.w}"><figcaption>${f.T.toFixed(2)}s · ${f.beat}<br>${f.phase} · units ${f.units} · ${f.form}</figcaption></figure>`).join("")}</div>`).join("");
    await sheet.setContent(html);
    const file = `aura-film-${bot.toLowerCase()}${tier === "M" ? "-m" : ""}${themes.length > 1 || dark ? `.${theme}` : ""}.png`;
    await sheet.screenshot({ path: path.join(flags.out, file), fullPage: true });
    console.log(`wrote ${file}`);
  }
  await sheet.close();
  await view.close();
}
await writeFile(path.join(flags.out, `aura-film${tier === "M" ? "-m" : ""}.json`), `${JSON.stringify(report, null, 2)}\n`);
await browser.close(); await server.close();
process.exit(failures ? 1 : 0);
