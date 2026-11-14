import { lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { useLineStatus } from "./chat/ChatSessionProvider";
import { notify } from "@/components/state/notify";
import { botIdOfLine, newlyListed } from "../chat-states.mjs";
import { translatePhrase } from "../i18n";
import { useBots } from "../BotPages";
import { OptionalChunk } from "../OptionalChunk";
import { isResearchSection, navGroup, type WorkspaceSection } from "../workspace-sections.mjs";
import { getChatMode, getResearchQueue, markBotRead, putResearchQueue, type Bot } from "../api";
import { normalizeHash } from "../legacy-routes.mjs";
import { pathForSection, paths, sectionOfPath, splitPath, symbolFromParams, symbolParam } from "../routes.mjs";
import { MAX_WATCHLIST, normalizeTicker, normalizeWatchlist, selectionForWatchlist } from "../watchlist.mjs";
import { registerWatchlistAdder, setWatchlistSnapshot } from "../watchlist-bridge.mjs";
import type { PaletteData } from "@/components/command/CommandMenu";
import { WorkspaceContext, type Workspace } from "./workspace";
import { AppShell } from "./shell/AppShell";
import { useRoutinesBadge } from "./shell/useRoutinesBadge";

// The new-bot dialog is only needed when 新建 is pressed: its own chunk, fetched on demand.
const NewBotDialog = lazy(() => import("../BotSidePanel").then((module) => ({ default: module.NewBotDialog })));

export const DEFAULT_SYMBOL = "AAPL";
export const DEFAULT_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"];
const WATCHLIST_KEY = "market-evidence-agent:watchlist:v1";
export const SELECTED_SYMBOL_KEY = "market-evidence-agent:selected-symbol:v1";

/** The reader's last company: a stored preference, used where an address names none. */
export function storedSymbol(): string | null {
  try { return normalizeTicker(localStorage.getItem(SELECTED_SYMBOL_KEY)); } catch { return null; }
}

/** The company an address names (a company page's path, or ?symbol= on the library and evidence pages); null when it names none. */
function symbolOfAddress(pathname: string, search: string): string | null {
  const company = /^\/research\/c\/([^/]+)/.exec(pathname);
  if (company) { try { return normalizeTicker(symbolParam(decodeURIComponent(company[1]))); } catch { return null; } }
  if (pathname === paths.materials().split("?")[0] || pathname === paths.evidenceIndex().split("?")[0]) return symbolFromParams(new URLSearchParams(search));
  return null;
}

/**
 * The workspace around every routed page: the research queue (kept on the server for the owner), the bot list, the
 * agent's client actions, and the shell (sidebar, tab bar, login dialog: app/shell).  It is what WorkspaceApp in App.tsx
 * used to be, minus the page switch: the router decides the page, and this only reads the address for what the chrome
 * needs (the highlighted section, the company the picker shows, the open bot).
 */
export function WorkspaceLayout({ onModeChange }: { onModeChange: (mode: "guest" | "personal" | null) => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [symbols, setSymbols] = useState<string[]>(() => { try { return normalizeWatchlist(JSON.parse(localStorage.getItem(WATCHLIST_KEY) ?? "null"), DEFAULT_SYMBOLS); } catch { return DEFAULT_SYMBOLS; } });
  const [preferred, setPreferred] = useState(() => storedSymbol() ?? DEFAULT_SYMBOL);
  const [watchInput, setWatchInput] = useState("");
  const [watchError, setWatchError] = useState("");
  const [newBotOpen, setNewBotOpen] = useState(false);
  const addressPath = location.pathname + location.search;
  const activeSection = sectionOfPath(addressPath) as WorkspaceSection;
  const addressSymbol = symbolOfAddress(location.pathname, location.search);
  const symbol = addressSymbol ?? preferred;
  const symbolRef = useRef(symbol); symbolRef.current = symbol;
  const preferredRef = useRef(preferred); preferredRef.current = preferred;
  const sectionRef = useRef(activeSection); sectionRef.current = activeSection;
  const addressRef = useRef(addressPath); addressRef.current = addressPath;

  const setPreferredSymbol = useCallback((next: string) => setPreferred(next), []);
  useEffect(() => { try { localStorage.setItem(SELECTED_SYMBOL_KEY, preferred); } catch { /* optional preference */ } }, [preferred]);
  // Opening a company's own address makes it the reader's last company.
  useEffect(() => { if (addressSymbol) setPreferred(addressSymbol); }, [addressSymbol]);
  useEffect(() => { try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(symbols)); } catch { /* optional preference */ } }, [symbols]);
  // The queue the chat request carries, and the add the agent's "not in your research queue" card uses.
  useEffect(() => { setWatchlistSnapshot(symbols); }, [symbols]);
  useEffect(() => registerWatchlistAdder((raw: string) => {
    const ticker = normalizeTicker(raw);
    if (ticker) setSymbols(items => items.includes(ticker) || items.length >= MAX_WATCHLIST ? items : [...items, ticker]);
  }), []);

  // The company switch of the shell and the agent's select_stock: the same kind of page, for the other company.
  const switchSymbol = useCallback((ticker: string) => {
    const section = sectionRef.current, address = splitPath(addressRef.current);
    const tab = new URLSearchParams(address.params).get("tab");
    setPreferred(ticker);
    if (section === "materials") navigate(tab === "materials" ? paths.company(ticker, "materials") : paths.materials({ symbol: ticker }));
    else if (section === "evidence") navigate(paths.evidenceIndex({ symbol: ticker }));
    else if (section === "forecast" && tab === "forecasts") navigate(paths.company(ticker, "forecasts"));
    else navigate(paths.company(ticker));
  }, [navigate]);
  const go = useCallback((section: WorkspaceSection) => navigate(pathForSection(section, symbolRef.current)), [navigate]);

  useEffect(() => {
    const receive = (event: Event) => {
      const action = (event as CustomEvent).detail;
      if (action.action === "queue_add") setSymbols(items => items.includes(action.symbol) || items.length >= MAX_WATCHLIST ? items : [...items, action.symbol]);
      if (action.action === "queue_remove") setSymbols(items => items.filter(item => item !== action.symbol));
      if (action.action === "queue_sync") setSymbols(action.symbols);
      if (action.action === "select_stock") switchSymbol(action.symbol);
      if (action.action === "open_page") {
        // The page names the agent knows, renamed as they always were, then through the old-address list.
        const name = ({ predictions: "forecast", sec: "evidence", knowledge: "admin" } as Record<string, string>)[action.page] ?? action.page;
        navigate(normalizeHash(`#${name}`, { lastSymbol: preferredRef.current }) ?? paths.chat());
      }
    };
    window.addEventListener("market-evidence-agent:client-action", receive);
    return () => window.removeEventListener("market-evidence-agent:client-action", receive);
  }, [navigate, switchSymbol]);

  // The owner's queue lives in the database (clearing the browser must not clear it); a guest's stays in the
  // browser.  The browser copy is the cache: it shows at once, and the server's copy replaces it when read.
  const personal = getChatMode() === "personal";
  const [queueReady, setQueueReady] = useState(!personal);
  const lastSavedQueue = useRef("");
  useEffect(() => {
    if (!personal) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const saved = await getResearchQueue(controller.signal);
        if (controller.signal.aborted) return;
        if (saved === null) {
          // First time: the list this browser holds becomes the owner's.
          lastSavedQueue.current = JSON.stringify(symbols);
          await putResearchQueue(symbols, controller.signal);
        } else {
          const clean = [...new Set(saved.map(normalizeTicker).filter((item): item is string => Boolean(item)))].slice(0, MAX_WATCHLIST);
          lastSavedQueue.current = JSON.stringify(clean);
          setSymbols(clean);
        }
      } catch { /* offline, or the server copy is not readable: the browser copy stays */ }
      finally { if (!controller.signal.aborted) setQueueReady(true); }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personal]);
  useEffect(() => {
    if (!personal || !queueReady) return;
    const body = JSON.stringify(symbols);
    if (body === lastSavedQueue.current) return;
    lastSavedQueue.current = body;
    void putResearchQueue(symbols).catch(() => { /* the browser copy still holds it */ });
  }, [symbols, personal, queueReady]);
  useEffect(() => { if (symbols.length) setPreferred(current => selectionForWatchlist(current, symbols)); }, [symbols]);

  // Bots (owner only): the sidebar lists them; /chat is the default bot's line, /chat/<id> another's.
  const lineStatus = useLineStatus();
  const botList = useBots(personal);
  // A background answer finished: refresh the list so its last line and unread count are current.
  const unseenCount = lineStatus.unseen.length, reloadBotsRef = useRef(botList.reload); reloadBotsRef.current = botList.reload;
  useEffect(() => { if (unseenCount) void reloadBotsRef.current(); }, [unseenCount]);
  const botParam = activeSection === "bot" ? (location.pathname.split("/")[2] ?? "").toLowerCase() : null;
  const activeBot: Bot | null = !personal ? null : botParam ? botList.bots.find(b => b.id === botParam) ?? null : location.pathname === paths.chat() ? botList.defaultBot : null;
  // Opening a bot's line marks its posted briefs read once, then the list refreshes so the badge clears.
  const openedBotId = activeBot?.id ?? null, reloadBots = botList.reload;
  useEffect(() => { if (openedBotId) void markBotRead(openedBotId).then(() => reloadBots()).catch(() => { /* the badge stays until the next refresh */ }); }, [openedBotId, reloadBots]);
  const openBot = useCallback((bot: Bot) => navigate(bot.is_default ? paths.chat() : paths.chat(bot.id)), [navigate]);
  // A background answer finished while the reader was in another line or page: a toast that takes them there.  One per bot (its id replaces the last), so a run of answers does not pile up.
  const unseenLines = lineStatus.unseen, seenBefore = useRef<string[]>([]);
  useEffect(() => {
    const fresh = newlyListed(seenBefore.current, unseenLines); seenBefore.current = unseenLines;
    for (const key of fresh) {
      const bot = botList.bots.find(item => item.id === botIdOfLine(key));
      if (bot) notify.info(`${bot.name} ${translatePhrase("回答好了")}`, { id: `background-done:${bot.id}`, action: { label: translatePhrase("查看"), onClick: () => openBot(bot) } });
    }
  }, [unseenLines.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const openCompany = useCallback((ticker: string, view: "overview" | "forecast" = "overview") => {
    const clean = normalizeTicker(ticker);
    if (!clean) return;
    setSymbols(items => items.includes(clean) || items.length >= MAX_WATCHLIST ? items : [...items, clean]);
    setPreferred(clean);
    navigate(view === "forecast" ? paths.company(clean, "forecasts") : paths.company(clean));
  }, [navigate]);
  function addWatchSymbol() {
    const ticker = normalizeTicker(watchInput);
    if (!ticker) { setWatchError("请输入有效的美股代码，例如 AMD 或 BRK.B。"); return; }
    if (symbols.includes(ticker)) { setWatchError("该代码已在关注列表中。"); return; }
    if (symbols.length >= MAX_WATCHLIST) { setWatchError("关注列表最多保存 30 个代码。"); return; }
    setSymbols(items => [...items, ticker]); setWatchInput(""); setWatchError("");
    // A company just added opens on its overview, wherever the reader was.
    setPreferred(ticker); navigate(paths.company(ticker));
  }
  const removeWatchSymbol = useCallback((ticker: string) => {
    const remaining = symbols.filter(item => item !== ticker);
    setSymbols(remaining);
    const next = selectionForWatchlist(preferredRef.current, remaining);
    setPreferred(next);
    // The page was about the company just removed: it moves to the one the queue now starts with.
    if (symbolRef.current === ticker && next && sectionRef.current === "overview") navigate(addressSymbol ? paths.company(next) : paths.research(), { replace: true });
  }, [symbols, navigate, addressSymbol]);

  const workspace: Workspace = useMemo(() => ({
    personal, symbols, setSymbols, symbol, preferredSymbol: preferred, setPreferredSymbol, bots: botList, go, openCompany, removeWatchSymbol, openNewBot: () => setNewBotOpen(true),
  }), [personal, symbols, symbol, preferred, setPreferredSymbol, botList, go, openCompany, removeWatchSymbol]);

  const newBotDialog = newBotOpen && <OptionalChunk><NewBotDialog onClose={() => setNewBotOpen(false)} onCreated={bot => { setNewBotOpen(false); void botList.reload().then(() => openBot(bot)); }} /></OptionalChunk>;
  // The to-do number is read again whenever the bot list reloads (every action on the 任务 page and every finished answer reloads it).
  const routinesCount = useRoutinesBadge(personal, botList.bots);
  // The old top bar showed the company switcher on the research pages, except the forecast group (its company comes from the record).
  const stockPicker = isResearchSection(activeSection) && navGroup(activeSection) !== "forecast";
  // What the command palette lists: the same watch list, bot list and company switch the sidebar and the research bar use.
  const palette: PaletteData = { personal, symbol, symbols, bots: botList.bots, onSelectCompany: switchSymbol, onAddCompany: openCompany };
  return <AppShell onModeChange={onModeChange} overlay={newBotDialog} palette={palette}
    nav={{ path: addressPath, personal, symbol, bots: botList.bots, botsError: botList.error, activeBotId: activeBot?.id ?? null, lineStatus, routinesCount, onNewBot: () => setNewBotOpen(true), onModeChange }}
    research={stockPicker ? { symbol, symbols, onSelectStock: switchSymbol, watchInput, setWatchInput, addWatchSymbol, watchError, setWatchError } : null}>
    <WorkspaceContext.Provider value={workspace}><Outlet /></WorkspaceContext.Provider>
  </AppShell>;
}
