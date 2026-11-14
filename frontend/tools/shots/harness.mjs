// Shared browser plumbing for run.mjs and smoke.mjs: one deterministic context per page view.
import { chromium } from "playwright-core";
import { installMockApi, FAKE_CREDENTIAL } from "./mock-api.mjs";

/** 2026-11-13 10:00 Beijing time. */
export const FIXED_TIME = new Date("2026-11-13T02:00:00.000Z");
export const HEIGHTS = { 390: 844, 768: 1024, 1440: 900 };
const THEME_KEY = "market-evidence-agent:theme:v1";
const LOCALE_KEY = "market-evidence-agent:locale:v1";
const MODE_KEY = "market-evidence-agent:chat-mode:v1";
const PERSONAL_KEY = "market-evidence-agent:personal-chat-session:v1";

export async function launch() {
  return chromium.launch({ headless: true, args: ["--force-color-profile=srgb", "--disable-lcd-text", "--font-render-hinting=none", "--disable-gpu", "--disable-gpu-rasterization", "--num-raster-threads=1", "--disable-threaded-animation", "--disable-partial-raster", "--disable-composited-antialiasing"] });
}

/** Runs in every document before the app: seeded Math.random, preset storage, animations off. */
function initScript({ theme, locale, credential, seed, motion }) {
  let state = seed >>> 0;
  Math.random = () => { // mulberry32
    state = (state + 0x6D2B79F5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  try {
    if (!localStorage.getItem("market-evidence-agent:theme:v1")) localStorage.setItem("market-evidence-agent:theme:v1", theme);
    if (!localStorage.getItem("market-evidence-agent:locale:v1")) localStorage.setItem("market-evidence-agent:locale:v1", locale);
    if (credential && !localStorage.getItem("market-evidence-agent:chat-mode:v1")) {
      localStorage.setItem("market-evidence-agent:chat-mode:v1", "personal");
      localStorage.setItem("market-evidence-agent:personal-chat-session:v1", credential);
    }
  } catch { /* storage unavailable: the page will show its own state */ }
  const css = "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important}";
  const inject = () => {
    if (document.getElementById("shots-no-motion")) return;
    const style = document.createElement("style"); style.id = "shots-no-motion"; style.textContent = css;
    (document.head ?? document.documentElement).appendChild(style);
  };
  if (motion) return; // a view that measures real animation keeps the page's own CSS motion
  if (document.documentElement) inject();
  else new MutationObserver((_, observer) => { if (document.documentElement) { inject(); observer.disconnect(); } }).observe(document, { childList: true });
  document.addEventListener("DOMContentLoaded", inject);
}

/**
 * A fresh, deterministic browser context.
 * opts: { width, height?, theme, locale, identity: "personal"|"none", label, unmatched, seed?, motion?, fixtureState? }
 * `motion: true` keeps real motion (no reduced-motion preference, no animation-killing style) for checks that measure it.
 * `fixtureState` replaces the default fake backend state (see fixtures/index.mjs buildState).
 */
export async function newView(browser, opts) {
  const { width, theme = "light", locale = "zh-CN", identity = "personal", label, unmatched, seed = 20261113, motion = false, fixtureState } = opts;
  const height = opts.height ?? HEIGHTS[width] ?? 900;
  const context = await browser.newContext({
    viewport: { width, height }, deviceScaleFactor: 1, locale, timezoneId: "Asia/Shanghai",
    reducedMotion: motion ? "no-preference" : "reduce", colorScheme: theme, serviceWorkers: "block", acceptDownloads: false,
  });
  await context.addInitScript(initScript, { theme, locale, credential: identity === "personal" ? FAKE_CREDENTIAL : null, seed, motion });
  await context.clock.setFixedTime(FIXED_TIME);
  const mock = await installMockApi(context, { label, unmatched, ...(fixtureState ? { fixtureState } : {}) });
  const page = await context.newPage();
  const problems = { console: [], pageErrors: [] };
  page.on("console", (message) => { if (message.type() === "error") problems.console.push({ text: message.text().slice(0, 300), url: message.location()?.url ?? "" }); });
  page.on("pageerror", (error) => problems.pageErrors.push(String(error?.stack ?? error).slice(0, 400)));
  return { context, page, mock, problems, close: () => context.close() };
}

/**
 * Wait until the page is quiet: network idle, fonts loaded, two animation frames.  The chat transcript follows
 * its newest line by itself, and when that happens relative to late layout varies; pinning it to the bottom
 * makes the picture independent of that race (pass { pinTranscript: false } to leave a scripted position alone).
 */
export async function settle(page, { pinTranscript = true } = {}) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(async (pin) => {
    await document.fonts?.ready;
    const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    await frame();
    // A native <select> lays its inner text out once, when it is created; if the web font lands after that, Chrome
    // does not lay the text out again and it sits 1px off, depending on load timing.  Force one layout now that the
    // fonts are ready, so the picture no longer depends on when the page mounted the control.
    const selects = [...document.querySelectorAll("select")];
    if (selects.length) {
      const shown = selects.map((el) => el.style.display);
      selects.forEach((el) => { el.style.display = "none"; });
      void document.body.offsetHeight;
      selects.forEach((el, i) => { el.style.display = shown[i]; });
      await frame();
    }
    if (pin) { document.querySelectorAll(".agent-transcript").forEach((el) => { el.scrollTop = el.scrollHeight; }); await frame(); }
  }, pinTranscript);
}

export { THEME_KEY, LOCALE_KEY, MODE_KEY, PERSONAL_KEY };
