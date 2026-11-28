const memorySeen = new WeakMap();
const actions = new Set(['queue_add','queue_remove','queue_sync','show_queue','select_stock','open_page']);
const ticker = /^[A-Z]{1,5}(?:\.[A-Z]{1,2})?$/;
// The pages the assistant's open_page names (the server's PAGE_PATHS in app/agent_tool_catalog.py holds the same table): the old engine's
// nine open through the workspace's old-address list; the rest (11-28) open their own address.
export const PAGE_PATHS = {
  overview: '/research', predictions: '/research/forecasts', materials: '/research/materials', sec: '/research/evidence', revisions: '/research/forecasts',
  evaluation: '/research/scores', agent: '/chat', knowledge: '/assistant/knowledge', memory: '/assistant/memory',
  settings_models: '/settings/models', settings_notifications: '/settings/notifications', settings_appearance: '/settings/appearance',
  settings_data: '/settings/data', settings_account: '/settings/account', routines: '/routines', work: '/routines?tab=work',
  portfolio: '/portfolio', bots: '/assistant/bots', skills: '/assistant/skills', news: '/assistant/news', backstage: '/backstage',
};
export const OLD_PAGES = new Set(['overview','predictions','materials','sec','revisions','evaluation','agent','knowledge','memory']);
const pages = new Set(Object.keys(PAGE_PATHS));
export function dispatchAgentAction(data, host = globalThis) {
  if (!data || typeof data.id !== 'string' || !/^[a-f0-9-]{36}$/.test(data.id) || !actions.has(data.action)) return false;
  if (['queue_add','queue_remove','select_stock'].includes(data.action) && !ticker.test(data.symbol ?? '')) return false;
  if (data.action === 'open_page' && !pages.has(data.page)) return false;
  if (data.action === 'queue_sync' && (!Array.isArray(data.symbols) || data.symbols.length > 30 || !data.symbols.every(x=>ticker.test(x)))) return false;
  const key = 'market-evidence-agent:applied-client-actions:v1';
  let seen=memorySeen.get(host) || [];
  try { const saved=JSON.parse(host.sessionStorage.getItem(key) || '[]'); if (Array.isArray(saved)) seen=[...new Set([...seen,...saved])]; } catch { /* optional storage */ }
  if (!Array.isArray(seen)) seen=[];
  if (seen.includes(data.id)) return false;
  memorySeen.set(host,[...seen,data.id].slice(-1000));
  host.dispatchEvent(new host.CustomEvent('market-evidence-agent:client-action', {detail:data}));
  try { host.sessionStorage.setItem(key,JSON.stringify([...seen,data.id].slice(-1000))); } catch { /* optional storage */ }
  return true;
}
