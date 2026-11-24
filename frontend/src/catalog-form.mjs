// Pure helpers of the server model catalog form (settings › 服务器模型目录, UX batch 3), kept apart so node tests
// read them.  The form replaced the browser model profiles: same fields, but the key goes to the server.

const KEYLESS_DISCOVERY = new Set(["openrouter"]);

/** True when an edited entry changed provider or endpoint: its stored key must not follow it there. */
export function entryMoved(entry) {
  if (!entry?.editing) return false;
  return entry.provider !== entry.editing.provider || (entry.base_url.trim() || null) !== (entry.editing.base_url || null);
}

/** The key a check (测试 / 服务商可用模型) uses: typed, an environment variable, or the stored one of the entry being
 *  edited (same provider and endpoint).  Null when there is none yet. */
export function probeFor(entry, { forDiscovery = false } = {}) {
  if (!entry) return null;
  const base = { provider: entry.provider, base_url: entry.base_url.trim() || null, ...(entry.model.trim() ? { model: entry.model.trim() } : {}) };
  if (entry.key_mode === "vault" && entry.api_key) return { ...base, api_key: entry.api_key };
  if (entry.key_mode === "env" && entry.key_env.trim()) return { ...base, key_env: entry.key_env.trim() };
  if (entry.editing && !entryMoved(entry) && entry.key_mode === entry.editing.key_source && entry.editing.key_status === "configured") return { ...base, name: entry.editing.name };
  if (forDiscovery && KEYLESS_DISCOVERY.has(entry.provider)) return base;
  return null;
}

/** A catalog name from what the owner typed: lowercase letters, digits and ._- , at most 40, not already taken. */
export function catalogName(source, taken = []) {
  const stem = String(source ?? "").toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[^a-z0-9]+/, "").replace(/-+$/, "").slice(0, 36) || "model";
  const used = new Set(taken);
  if (!used.has(stem)) return stem;
  for (let n = 2; n < 100; n++) if (!used.has(`${stem}-${n}`)) return `${stem}-${n}`;
  return `${stem}-${Date.now() % 1000}`;
}

/** The four optional prices of a model (USD per million tokens), in the order the form shows them. */
export const PRICE_FIELDS = ["price_input", "price_output", "price_cache_read", "price_cache_write"];
/** A price box's text as a number, null when it is empty, NaN when it is not a number from 0 up (the server refuses the same). */
export function parsePrice(text) {
  const value = String(text ?? "").trim();
  if (!value) return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 100000 ? number : Number.NaN;
}
/** A stored price as the text of its box. */
export const priceText = (value) => (value == null ? "" : String(value));

/** What 测试并保存 sends to save the entry once the test passed (a key only when one was given).  An edit sends all four
 *  prices (null clears one); a new entry sends the ones that were filled in. */
export function saveBody(entry) {
  const key = entry.key_mode === "vault" ? (entry.api_key ? { api_key: entry.api_key } : {}) : (entry.key_env.trim() ? { key_env: entry.key_env.trim() } : {});
  const prices = PRICE_FIELDS.map((field) => [field, parsePrice(entry[field])]).filter(([, value]) => entry.editing || value !== null);
  return { display_name: entry.display_name.trim() || undefined, provider: entry.provider, model: entry.model.trim(),
    base_url: entry.base_url.trim() || null, ...key, ...(entry.is_default ? { is_default: true } : {}), ...Object.fromEntries(prices) };
}

/** Why 测试并保存 cannot run yet, as a phrase, or "" when it can.  ``taken`` are the catalog names in use: an edit may keep
 *  its own name, but a new entry or a rename may not take another entry's. */
export function entryProblem(entry, taken = []) {
  if (!entry) return "";
  if (!entry.model.trim()) return "请填写 Model ID。";
  if (!/^[a-z0-9][a-z0-9._-]{0,39}$/.test(entry.name)) return "名字只能用小写字母、数字和 ._-。";
  if (entry.name !== entry.editing?.name && taken.includes(entry.name)) return "已有同名模型。";
  if (entry.provider === "custom" && !entry.base_url.trim()) return "自定义服务必须填写 Base URL。";
  if (PRICE_FIELDS.some((field) => Number.isNaN(parsePrice(entry[field])))) return "价格要填不小于 0 的数字，不填就不算花费。";
  if (!probeFor(entry)) return entryMoved(entry) ? "换了服务或接口地址，需要重新填写 key。" : "请填写 API key 或环境变量名。";
  return "";
}

/** The children of `main` to mark inert while the modal is open: every one except the one holding the modal (inert ancestors block clicks). */
export function siblingsToInert(main, modal) {
  return main ? [...main.children].filter((child) => !child.contains(modal)) : [];
}
