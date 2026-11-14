// Which way the market colours run: green up / red down (the default), or red up / green down.  Only the two
// market-direction tokens --up and --down trade places (tokens.css, keyed on <html data-updown>); success and error
// colours never move.  Same shape as theme.mjs: a storage key, a pure resolver, apply-to-root, save.
export const UPDOWN_KEY = "market-evidence-agent:updown:v1";
export const UPDOWNS = ["green-up", "red-up"];
export const DEFAULT_UPDOWN = "green-up";

export function storedUpdown(storage = globalThis.localStorage) {
  try { const value = storage?.getItem(UPDOWN_KEY); return UPDOWNS.includes(value) ? value : DEFAULT_UPDOWN; } catch { return DEFAULT_UPDOWN; }
}

export function applyUpdown(choice, root = globalThis.document?.documentElement) {
  const value = UPDOWNS.includes(choice) ? choice : DEFAULT_UPDOWN;
  if (root) root.dataset.updown = value;
  return value;
}

export function saveUpdown(choice, storage = globalThis.localStorage) {
  if (!UPDOWNS.includes(choice)) return storedUpdown(storage);
  try { storage?.setItem(UPDOWN_KEY, choice); } catch { /* optional preference */ }
  return choice;
}
