// The evidence film of the handoff (A4): frames of the sample page's live stage at exact ages of a switch.  The clock is Playwright's fake one
// (`page.clock`), stepped 16 ms at a time, so the frames are what the real director, painter and engine draw at that age, not a recording.
//   * enter:   for each of the five archetypes, six frames of its entrance (from the swap's end to the end of the entrance), on one sheet;
//   * fin-to-tesla: ten frames of the whole handoff from FinBot to TeslaBot (leave, swap and swirl, entrance, the rings going);
//   * leave:   the same five, the exit (0 to 160 ms);
//   * rapid:   three bots in 200 ms: the stage goes straight to the last (frames of the first second).
// Usage: node handoff-film.mjs --dist <build dir> --out <dir> [--theme light|dark] [--only enter,fin-to-tesla,leave,rapid]
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { parseArgs, csv } from "./args.mjs";
import { startServer } from "./server.mjs";
import { launch, newView, settle } from "./harness.mjs";

const { flags } = parseArgs(process.argv.slice(2));
if (!flags.dist || !flags.out) { console.error("usage: node handoff-film.mjs --dist <dir> --out <dir> [--theme light|dark] [--only a,b]"); process.exit(2); }
const theme = flags.theme === "dark" ? "dark" : "light";
const only = csv(flags.only, ["enter", "fin-to-tesla", "leave", "rapid"]);
const NAMES = ["FinBot", "TeslaBot", "NewsBot", "AppleBot", "ReportBot"];
const STEP = 16;
const CLIP = { w: 360, h: 300 };

await mkdir(flags.out, { recursive: true });
const server = await startServer(flags.dist);
const browser = await launch();
const unmatched = [];
const view = await newView(browser, { width: 1440, theme, label: "handoff-film", unmatched, motion: true });
const { page } = view;
await page.goto(`${server.url}#/dev/kit/bots`, { waitUntil: "load" });
await page.waitForSelector("[data-testid=handoff-row]");
await settle(page);
await page.locator("[data-testid=handoff-stage]").scrollIntoViewIfNeeded();
await page.waitForTimeout(600);
await page.clock.install();
await page.clock.pauseAt(new Date(Date.now() + 5000));
const sheet = await browser.newPage({ viewport: { width: 2600, height: 600 } });

/** Shoot the stage at each of `ages` (seconds after the switch was asked for, ascending, multiples of 16 ms); returns [{ age, label, png, phase }]. */
async function strip(from, to, ages, { rapid = false } = {}) {
  await page.evaluate((i) => window.__handoffStage.stand(i), NAMES.indexOf(from));
  await page.clock.runFor(400);
  const t0 = await page.evaluate(() => performance.now());
  if (rapid) {
    const order = [to, ...rapid];
    await page.evaluate((i) => window.__handoffStage.become(i), NAMES.indexOf(order[0]));
  } else await page.evaluate((i) => window.__handoffStage.become(i), NAMES.indexOf(to));
  let now = 0;
  const frames = [];
  const extra = rapid ? [[0.1, rapid[0]], [0.2, rapid[1]]] : [];
  for (const age of ages) {
    while (extra.length && extra[0][0] <= age + 1e-9) { const [at, name] = extra.shift(); await page.clock.runFor(Math.max(0, Math.round((at - now) * 1000))); now = at; await page.evaluate((i) => window.__handoffStage.become(i), NAMES.indexOf(name)); }
    const ms = Math.round(Math.max(0, age - now) * 1000 / STEP) * STEP;
    if (ms) await page.clock.runFor(ms);
    now += ms / 1000;
    const info = await page.evaluate(() => { const svg = document.querySelector("[data-testid=handoff-stage] svg"), aura = svg.querySelector("[data-slot=bot-aura]"); return { phase: svg.dataset.handoff || "-", state: svg.dataset.state, shape: svg.dataset.shape, aura: aura?.dataset.auraPhase ?? "-", variant: aura?.dataset.auraVariant ?? "-" }; });
    const avatar = page.locator("[data-testid=handoff-stage] [data-slot=bot-avatar]");
    const box = await avatar.boundingBox();
    const png = await page.screenshot({ clip: { x: box.x + box.width / 2 - CLIP.w / 2, y: box.y + box.height / 2 - CLIP.h / 2, width: CLIP.w, height: CLIP.h }, animations: "allow" });
    frames.push({ age: Math.round(now * 1000), info, src: `data:image/png;base64,${png.toString("base64")}` });
  }
  void t0;
  return frames;
}

async function write(file, title, rows) {
  const dark = theme === "dark";
  const html = `<style>body{margin:10px;background:${dark ? "#101010" : "#f4f3ef"};font:12px sans-serif;color:${dark ? "#ddd" : "#222"}}h2{margin:6px 0}.row{display:flex;gap:4px;margin-bottom:10px}figure{margin:0;text-align:center}figcaption{white-space:pre;line-height:1.4}img{display:block;border:1px solid ${dark ? "#333" : "#ddd"};background:${dark ? "#161616" : "#fff"}}</style>`
    + `<h1 style="font-size:16px">${title}</h1>`
    + rows.map(r => `<h2>${r.label}</h2><div class="row">${r.frames.map(f => `<figure><img src="${f.src}" width="${CLIP.w * 0.8}"/><figcaption>${f.age} ms\n${f.info.phase} · ${f.info.state}\naura ${f.info.aura}</figcaption></figure>`).join("")}</div>`).join("");
  await sheet.setContent(html);
  await sheet.screenshot({ path: path.join(flags.out, file), fullPage: true });
  console.log(`wrote ${file}`);
}
const suffix = theme === "dark" ? ".dark" : "";

if (only.includes("enter")) {
  const rows = [];
  const ages = [0.42, 0.5, 0.58, 0.66, 0.74, 0.84];
  for (const name of NAMES) rows.push({ label: `${name === "FinBot" ? "TeslaBot → FinBot" : `FinBot → ${name}`} · entrance of ${name}`, frames: await strip(name === "FinBot" ? "TeslaBot" : "FinBot", name, ages) });
  await write(`handoff-film-enter${suffix}.png`, "Entrance of each archetype (6 frames: 420-840 ms after the click; the swirl is still turning)", rows);
}
if (only.includes("fin-to-tesla")) {
  const ages = [0.03, 0.1, 0.16, 0.26, 0.38, 0.46, 0.58, 0.74, 1.0, 1.4];
  await write(`handoff-film-fin-to-tesla${suffix}.png`, "FinBot → TeslaBot, the whole handoff (10 frames)", [{ label: "0 ms = the click", frames: await strip("FinBot", "TeslaBot", ages) }]);
}
if (only.includes("leave")) {
  const rows = [];
  for (const name of NAMES) rows.push({ label: `exit of ${name} (→ ${name === "FinBot" ? "TeslaBot" : "FinBot"})`, frames: await strip(name, name === "FinBot" ? "TeslaBot" : "FinBot", [0.016, 0.048, 0.08, 0.112, 0.16, 0.24]) });
  await write(`handoff-film-leave${suffix}.png`, "Exit of each archetype (the old aura leaves in 120 ms; the new silhouette takes over at 120 ms)", rows);
}
if (only.includes("rapid")) {
  const ages = [0.05, 0.14, 0.24, 0.34, 0.5, 0.7, 0.95, 1.5];
  await write(`handoff-film-rapid${suffix}.png`, "FinBot → (TeslaBot at 0, NewsBot at 100 ms, ReportBot at 200 ms): the stage goes to the last, the ones between are not played", [{ label: "frames", frames: await strip("FinBot", "TeslaBot", ages, { rapid: ["NewsBot", "ReportBot"] }) }]);
}
await sheet.close(); await view.close(); await browser.close(); await server.close();
