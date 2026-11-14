// The evidence film of design 6.7's second table (A4): each way a handoff can land, as frames of the real chat page at exact ages after the click.
// The page's clock is Playwright's fake one (`page.clock`), paused and stepped 16 ms at a time after the page is set up, so a frame is what the
// real page draws at that age.  Each frame is the top of the chat column (the header's avatar and the thread under it); one sheet per case.
//   unread, working, waiting, rapid (three clicks 80 ms apart), phone (the bot switcher drawer, the line slides), reduced (the system asks for less)
// The CSS animations of the handoff (the new thread's entrance) are paused and set to each frame's age too.
// Usage: node handoff-cases.mjs --dist <build dir> --out <dir> [--only unread,working,...]
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { parseArgs, csv } from "./args.mjs";
import { startServer } from "./server.mjs";
import { FIXED_TIME, launch, newView, settle } from "./harness.mjs";
import { PAGES, clickSend, fillDraft, waitReady } from "./pages.mjs";
import { ASK_MARKER, HOLD_MARKER } from "./fixtures/ids.mjs";

const { flags } = parseArgs(process.argv.slice(2));
if (!flags.dist || !flags.out) { console.error("usage: node handoff-cases.mjs --dist <dir> --out <dir> [--only a,b]"); process.exit(2); }
const only = csv(flags.only, ["unread", "working", "waiting", "rapid", "phone", "reduced"]);
await mkdir(flags.out, { recursive: true });
const server = await startServer(flags.dist);
const browser = await launch();
const unmatched = [];
const sheet = await browser.newPage({ viewport: { width: 2800, height: 700 } });

async function open({ width = 1440, reduced = false } = {}) {
  const view = await newView(browser, { width, theme: "light", label: "handoff-cases", unmatched, motion: true });
  if (reduced) await view.page.emulateMedia({ reducedMotion: "reduce" });
  await view.page.goto(`${server.url}#/chat`, { waitUntil: "load" });
  await waitReady(view.page, PAGES.find((p) => p.name === "chat-default"));
  await settle(view.page);
  await view.page.waitForTimeout(1000);
  return view;
}
const row = (page, name) => page.locator("[data-bot-row]", { hasText: name }).first();
// the clock restarts from the harness's fixed time plus what the setup took (a card made in the setup must not have run out)
const pause = async (page) => { const start = new Date(FIXED_TIME.getTime() + 20000); await page.clock.install({ time: start }); await page.clock.pauseAt(new Date(start.getTime() + 1000)); };

/** Frames at `ages` (seconds after `start()` ran), the clock stepped to each one; `during` runs at its own ages (a click in the middle of a run). */
async function frames(page, start, ages, { clip, during = [] } = {}) {
  const t0 = await page.evaluate(() => performance.now());
  await start();
  const out = [], pending = [...during];
  let now = 0;
  for (const age of ages) {
    while (pending.length && pending[0].at <= age + 1e-9) { const step = pending.shift(); const ms = Math.round(Math.max(0, step.at - now) * 1000 / 16) * 16; if (ms) await page.clock.runFor(ms); now += ms / 1000; await step.run(); }
    const ms = Math.round(Math.max(0, age - now) * 1000 / 16) * 16;
    if (ms) await page.clock.runFor(ms);
    now += ms / 1000;
    // CSS animations run on the document's own timeline, not on the fake clock: lay the handoff's (the thread coming in, the old thread fading) on this age
    await page.evaluate((ms) => document.getAnimations().filter((a) => String(a.animationName ?? "").startsWith("handoff-")).forEach((a) => { a.pause(); a.currentTime = ms; }), Math.round(now * 1000));
    const info = await page.evaluate(() => { const svg = document.querySelector("[data-testid=chat-header] svg[data-slot=bot-body]"), t = document.querySelector("[data-testid=transcript]"); return { h: svg?.dataset.handoff || "-", pose: svg?.dataset.pose ?? "-", state: svg?.dataset.state ?? "-", shape: svg?.dataset.shape ?? "-", dot: svg?.dataset.waiting ?? "-", gaze: svg?.dataset.gaze ?? "-", title: document.querySelector("h1")?.textContent ?? "", entry: t?.dataset.entry ?? "-" }; });
    const box = await page.locator("[data-testid=chat-column]").boundingBox(), head = await page.locator("[data-testid=chat-header]").boundingBox();
    const png = await page.screenshot({ clip: { x: clip?.x ?? box.x, y: head.y, width: clip?.width ?? Math.min(box.width, 760), height: clip?.height ?? 520 }, animations: "allow" });
    out.push({ age: Math.round(now * 1000), info, src: `data:image/png;base64,${png.toString("base64")}` });
  }
  void t0;
  return out;
}
async function write(file, title, list, scale = 0.55) {
  const html = `<style>body{margin:10px;background:#f4f3ef;font:12px sans-serif;color:#222}.row{display:flex;gap:4px}figure{margin:0}figcaption{white-space:pre;line-height:1.4;text-align:center}img{display:block;border:1px solid #ddd}</style><h1 style="font-size:16px">${title}</h1><div class="row">`
    + list.map((f) => `<figure><img src="${f.src}" width="${Math.round(760 * scale)}"/><figcaption>${f.age} ms · ${f.info.title}\n${f.info.h} · ${f.info.state} · ${f.info.pose}\ngaze ${f.info.gaze} · dot ${f.info.dot} · entry ${f.info.entry}</figcaption></figure>`).join("") + "</div>";
  await sheet.setContent(html);
  await sheet.screenshot({ path: path.join(flags.out, file), fullPage: true });
  console.log(`wrote ${file}`);
}

if (only.includes("unread")) {
  const view = await open(); const { page } = view;
  await pause(page);
  await write("handoff-case-unread.png", "FinBot → NewsBot (unread): after the handoff the eyes glance at the divider for 0.8 s (frames at 1.4-2.3 s), then rest", await frames(page, () => row(page, "NewsBot").click(), [0.05, 0.3, 0.7, 1.2, 1.45, 1.8, 2.2, 2.6]), 0.45);
  await view.close();
}
if (only.includes("working")) {
  const view = await open(); const { page } = view;
  await row(page, "TeslaBot").click(); await page.locator("h1", { hasText: "TeslaBot" }).waitFor();
  await fillDraft(page, `${HOLD_MARKER} AAPL`, { botName: "TeslaBot" }); await clickSend(page); await page.locator("[data-testid=stop]").waitFor();
  await row(page, "FinBot").click(); await page.locator("h1", { hasText: "FinBot" }).waitFor(); await page.waitForTimeout(1500);
  await pause(page);
  await write("handoff-case-working.png", "FinBot → TeslaBot (answering in the background): no swirl, no entrance; it lands in its working pose", await frames(page, () => row(page, "TeslaBot").click(), [0.05, 0.2, 0.4, 0.7, 1.1, 1.6]), 0.5);
  await view.close();
}
if (only.includes("waiting")) {
  const view = await open(); const { page } = view;
  await row(page, "TeslaBot").click(); await page.locator("h1", { hasText: "TeslaBot" }).waitFor();
  await fillDraft(page, `${ASK_MARKER} 哪一个`, { botName: "TeslaBot" }); await clickSend(page);
  await page.locator('[data-slot="approval-card"][data-state="active"]').waitFor({ timeout: 15000 });
  await row(page, "NewsBot").click(); await page.locator("h1", { hasText: "NewsBot" }).waitFor(); await page.waitForTimeout(1500);
  await pause(page);
  await write("handoff-case-waiting.png", "NewsBot → TeslaBot (waits for you at a card): the amber dot is up at once, the swirl plays around it, the line opens at the card", await frames(page, () => row(page, "TeslaBot").click(), [0.05, 0.2, 0.4, 0.8, 1.4, 2.2]), 0.5);
  await view.close();
}
if (only.includes("rapid")) {
  const view = await open(); const { page } = view;
  await pause(page);
  const click = (name) => ({ run: () => page.evaluate((n) => [...document.querySelectorAll("[data-bot-row]")].find((r) => r.textContent.includes(n)).click(), name) });
  await write("handoff-case-rapid.png", "FinBot → TeslaBot (0 ms) → NewsBot (80 ms) → ReportBot (160 ms): content goes to the last at once, the avatar goes straight there, nothing of the two between is left", await frames(page, () => click("TeslaBot").run(), [0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 1.8], { during: [{ at: 0.08, ...click("NewsBot") }, { at: 0.16, ...click("ReportBot") }] }), 0.45);
  await view.close();
}
if (only.includes("phone")) {
  const view = await open({ width: 390 }); const { page } = view;
  // the drawer opens by its own animation (timers): open it before the clock is paused
  await page.locator("[data-testid=bot-switcher]").click(); await page.locator("[data-testid=bot-switcher-drawer]").waitFor(); await page.waitForTimeout(900);
  await pause(page);
  const clip = { x: 0, width: 390, height: 560 };
  const start = async () => { await page.locator("[data-bot-switch-row]", { hasText: "ReportBot" }).first().click(); };
  await write("handoff-case-phone.png", "Phone: FinBot → ReportBot from the switcher drawer (a later bot: the line slides in from the right, 24px and a fade)", await frames(page, start, [0.05, 0.12, 0.2, 0.3, 0.5, 1.0], { clip }), 0.9);
  await view.close();
}
if (only.includes("reduced")) {
  const view = await open({ reduced: true }); const { page } = view;
  await pause(page);
  await write("handoff-case-reduced.png", "Reduced motion: FinBot → NewsBot: the new silhouette at once, no swirl; the old line cross-fades into the new in 150 ms", await frames(page, () => row(page, "NewsBot").click(), [0.02, 0.06, 0.1, 0.16, 0.3, 0.8]), 0.5);
  await view.close();
}
await sheet.close(); await browser.close(); await server.close();
