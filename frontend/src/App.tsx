import { AgentAdminPage, AgentChatPanel, AgentChatProviderRoot, useLineStatus, useOpenConversation, useSelectBot } from "./AgentChatPanel";
import { BotRailList, BotSide, NewBotDialog, RoutineIcon, useBots } from "./BotPages";
import { BrandLogo } from "./BotOrb";
import { botFromHash } from "./bot-items.mjs";
import { Tx, formatDateTime as formatLocalizedDateTime, getLocalePreference, translatePhrase, useLocale } from "./i18n";
import { Suspense, lazy, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, markBotRead, type Bot, type EarningsJudgment, type V2ForecastList, getEarningsJudgments, getFilingInventory, getMaterialLibrary, getV2ForecastRoots, getV2Forecasts, getV2MonitorStatus, getV2Prices, initializeMarketData, scanOfficialFilings } from "./api";
import { forecastBySymbol, judgmentLane, type JudgmentLane } from "./forecast-home.mjs";
import { researchRecord } from "./portfolio-items.mjs";
import type { FilingInventory, PriceHistory } from "./types";
import { ModelScoresPage, modelStatusLabel } from "./ModelScoresPage";
import { ForecastPage } from "./ForecastPage";
import { ForecastHome } from "./ForecastHome";
import { EarningsJudgmentPage } from "./EarningsJudgmentPage";
import { ForecastMonitorPage } from "./ForecastMonitorPage";
import { parseForecastHash } from "./forecast-routes.mjs";
import { EvidenceCenter } from "./EvidenceCenter";
import { MaterialLibrary } from "./MaterialLibrary";
import { MATERIAL_FOCUS_KEY, materialLinkFromHash } from "./material-focus.mjs";
import { HistoricalReplayWorkspace } from "./HistoricalReplayWorkspace";
import { normalizeTicker, normalizeWatchlist, selectionForWatchlist, MAX_WATCHLIST } from "./watchlist.mjs";
import { getChatMode, setChatMode, personalChatLogin, getResearchQueue, putResearchQueue } from "./api";
import { registerWatchlistAdder, setWatchlistSnapshot } from "./watchlist-bridge.mjs";
import { chatSessionKey } from "./chat-session.mjs";
import { completePersonalLogin } from "./chat-mode-switch.mjs";
import { MemoryPage, MePage, NewsSourcesPage, RoutinesPage, SkillsPage } from "./PersonalPages";
import { PortfolioIcon, PortfolioPage } from "./PortfolioPage";
import { formatDelta } from "./delta.mjs";
import { conversationFromHash } from "./memory-items.mjs";

const DEFAULT_SYMBOL = "AAPL";
const DEFAULT_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"];
const WATCHLIST_KEY = "market-evidence-agent:watchlist:v1";
type SupportedSymbol = string;
type FilingState = { kind: "idle" } | { kind: "loading" } | { kind: "ready"; data: FilingInventory } | { kind: "error"; message: string };
type WorkspaceSection = "overview" | "forecast" | "evidence" | "materials" | "revisions" | "evaluation" | "replay" | "agent" | "bot" | "admin" | "routines" | "portfolio" | "news" | "skills" | "memory" | "me";
type ResearchSection = Exclude<WorkspaceSection, "agent" | "bot" | "admin" | "routines" | "portfolio" | "news" | "skills" | "memory" | "me">;
// The personal-agent navigation groups the older sections: 公司 holds 总览; 预测 holds the forecast home, one
// forecast's page, 模型成绩 (#evaluation) and 历史回放, and #revisions opens the versions of a forecast; 资料库 holds
// 材料库 and 证据.  Those six (公司、预测、资料库、技能、记忆、设置) are one 「更多」 control on the mobile tab bar and
// for guests.  On the desktop rail an owner has 预测 as a row of its own and the other five in 「更多」.
// 例行任务 is not one of them: it is a bot-rail row (with 持仓, 预测 and 新闻源 beside it) and its own mobile tab, so
// it stays primary chrome.  The older hashes stay the addresses, so links inside the older pages (#materials,
// #evidence/<id>/…) and the agent's open_page keep working unchanged.
type NavGroup = "chat" | "routines" | "portfolio" | "news" | "company" | "forecast" | "library" | "skills" | "memory" | "settings";
const FORECAST_TABS = ["forecast", "revisions", "evaluation", "replay"] as const;
// #revisions is still an address of the group, but it has no tab of its own: it is a part of one forecast's page.
const FORECAST_TAB_BUTTONS = ["forecast", "evaluation", "replay"] as const;
const LIBRARY_TABS = ["materials", "evidence"] as const;
// #briefs was the 待你确认 page; it is the 例行任务 page now.
const HASH_ALIASES: Record<string, WorkspaceSection> = { chat: "agent", company: "overview", library: "materials", settings: "admin", briefs: "routines" };
function navGroup(section: WorkspaceSection): NavGroup {
  if (section === "agent" || section === "bot") return "chat";
  if (section === "admin") return "settings";
  if (section === "routines" || section === "portfolio" || section === "news" || section === "skills" || section === "memory") return section;
  if (section === "me") return "memory";
  if ((LIBRARY_TABS as readonly string[]).includes(section)) return "library";
  if ((FORECAST_TABS as readonly string[]).includes(section)) return "forecast";
  return "company";
}
function isResearchSection(section: WorkspaceSection): section is ResearchSection { const group = navGroup(section); return group === "company" || group === "forecast" || group === "library"; }
const WORKSPACE_SECTION_TITLE: Record<ResearchSection, string> = {
  overview: "研究总览", forecast: "预测", evidence: "证据中心", materials: "材料库", revisions: "预测修订", evaluation: "模型成绩", replay: "历史回放",
};

// Developer sample page (#dev-kit).  The flag is a build-time constant, so a production build without VITE_DEV_KIT
// drops the dynamic import and the page's code never reaches dist.
const DEV_KIT_ENABLED = import.meta.env.DEV || import.meta.env.VITE_DEV_KIT === "1";
const DevKitPage = DEV_KIT_ENABLED ? lazy(() => import("./dev/KitPage")) : null;

// "#dev-kit/probe" opens the same page plus the scope probes the smoke checks use (kept off "#dev-kit" so its screenshots stay put).
const isDevKitHash = (hash: string) => hash === "#dev-kit" || hash === "#dev-kit/probe";

export function App() {
  const [devKit, setDevKit] = useState(() => isDevKitHash(window.location.hash));
  useEffect(() => {
    if (!DevKitPage) return;
    const read = () => setDevKit(isDevKitHash(window.location.hash));
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  if (DevKitPage && devKit) return <Suspense fallback={null}><DevKitPage /></Suspense>;
  // data-legacy marks the old UI for the restore block in styles/legacy/restore.css; display:contents keeps layout as it was.
  return <div data-legacy="" style={{ display: "contents" }}><AppEntry /></div>;
}

function AppEntry(){
  const {t}=useLocale();
  const [mode,setMode]=useState(()=>localStorage.getItem("market-evidence-agent:chat-mode:v1")?getChatMode():null),[code,setCode]=useState(""),[error,setError]=useState("");
  async function login(){try{const credential=await personalChatLogin(code);setChatMode("personal",credential);window.location.hash="agent";setMode("personal")}catch{setError("个人登录暂不可用，请检查登录码后重试。")}}
  if(mode)return <AgentChatProviderRoot key={chatSessionKey(mode,localStorage.getItem(mode==="personal"?"market-evidence-agent:personal-chat-session:v1":"market-evidence-agent:chat-session:v1"))}><WorkspaceApp key={mode} onModeChange={setMode}/></AgentChatProviderRoot>;
  return <main className="entry-choice"><p className="eyebrow">FinBot</p><h1>{t("选择聊天模式")}</h1><p>{t("访客与个人聊天记录保存在服务端 PostgreSQL。登录个人账户后即可进行站点操作。")}</p><div><button className="primary-action" onClick={()=>{setChatMode("guest");window.location.hash="agent";setMode("guest")}}>{t("继续访客聊天")}</button><label>{t("个人聊天登录码")}<input type="password" value={code} maxLength={256} autoComplete="current-password" onChange={e=>setCode(e.target.value)}/></label><button className="secondary-action" disabled={!code} onClick={()=>void login()}>{t("登录个人聊天")}</button>{error&&<p role="alert">{error}</p>}</div></main>;
}

function WorkspaceApp({onModeChange}:{onModeChange:(mode:"guest"|"personal")=>void}) {
  const [symbols, setSymbols] = useState<string[]>(() => { try { return normalizeWatchlist(JSON.parse(localStorage.getItem(WATCHLIST_KEY) ?? "null"), DEFAULT_SYMBOLS); } catch { return DEFAULT_SYMBOLS; } });
  const [requestedSymbol, setRequestedSymbol] = useState(() => { try { return normalizeTicker(localStorage.getItem("market-evidence-agent:selected-symbol:v1")) ?? DEFAULT_SYMBOL; } catch { return DEFAULT_SYMBOL; } });
  const [watchInput, setWatchInput] = useState("");
  const [watchError, setWatchError] = useState("");
  const [activeSection, setActiveSection] = useState<WorkspaceSection>(sectionFromHash());
  const [forecastRoute, setForecastRoute] = useState(() => parseForecastHash(window.location.hash));
  const [activeData, setActiveData] = useState<{ kind: "loading"; symbol: string } | { kind: "ready"; symbol: string; filings: FilingState; priceHistory: PriceHistory | null; priceError: string | null }>({ kind: "loading", symbol: DEFAULT_SYMBOL });
  const [retryKey, setRetryKey] = useState(0);
  const requestVersion = useRef(0);
  const activeSymbolRef = useRef(requestedSymbol);
  activeSymbolRef.current = requestedSymbol;
  useEffect(() => { try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(symbols)); } catch { /* optional preference */ } }, [symbols]);
  // The queue the chat request carries, and the add the agent's "not in your research queue" card uses.
  useEffect(() => { setWatchlistSnapshot(symbols); }, [symbols]);
  useEffect(() => registerWatchlistAdder((raw: string) => {
    const ticker = normalizeTicker(raw);
    if (ticker) setSymbols(items => items.includes(ticker) || items.length >= MAX_WATCHLIST ? items : [...items, ticker]);
  }), []);
  useEffect(() => {
    const receive = (event: Event) => {
      const action = (event as CustomEvent).detail;
      if (action.action === "queue_add") setSymbols(items => items.includes(action.symbol) || items.length >= MAX_WATCHLIST ? items : [...items, action.symbol]);
      if (action.action === "queue_remove") setSymbols(items => items.filter(item => item !== action.symbol));
      if (action.action === "queue_sync") setSymbols(action.symbols);
      if (action.action === "select_stock") setRequestedSymbol(action.symbol);
      if (action.action === "open_page") window.location.hash = ({predictions:"forecast",sec:"evidence",knowledge:"admin"} as Record<string,string>)[action.page] ?? action.page;
    };
    window.addEventListener("market-evidence-agent:client-action", receive);
    return () => window.removeEventListener("market-evidence-agent:client-action", receive);
  }, []);
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
  useEffect(() => { if (symbols.length) setRequestedSymbol(current => selectionForWatchlist(current, symbols)); }, [symbols]);
  useEffect(() => { try { localStorage.setItem("market-evidence-agent:selected-symbol:v1", requestedSymbol); } catch { /* optional preference */ } }, [requestedSymbol]);

  // A save reply's link (#materials?symbol=AAPL&focus=<id>) opens 资料库 on that stock and row.
  const [materialFocusKey, setMaterialFocusKey] = useState(0);
  useEffect(() => {
    const openMaterialLink = () => {
      const link = materialLinkFromHash(window.location.hash);
      if (!link) return;
      if (link.source_id) { try { sessionStorage.setItem(MATERIAL_FOCUS_KEY, JSON.stringify(link)); } catch { /* the list still opens */ } }
      setRequestedSymbol(link.symbol);
      setMaterialFocusKey((value) => value + 1);
    };
    openMaterialLink();
    const onHashChange = () => { setActiveSection(sectionFromHash()); setForecastRoute(parseForecastHash(window.location.hash)); openMaterialLink(); };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  // A past-conversation link (#agent/<id>, from recall_conversations) opens that conversation.
  const openConversation = useOpenConversation(), openRef = useRef(openConversation); openRef.current = openConversation;
  const selectBot = useSelectBot(), selectBotRef = useRef(selectBot); selectBotRef.current = selectBot;
  const lineStatus = useLineStatus();
  // A past conversation (from the memory page) opens outside any bot's line, read and continued as before.
  const [pastConversation, setPastConversation] = useState(false);
  useEffect(() => {
    const follow = () => {
      const id = conversationFromHash(window.location.hash);
      if (!id) return;
      window.history.replaceState(null, "", "#agent"); setActiveSection("agent"); setPastConversation(true);
      void selectBotRef.current(null).then(() => openRef.current(id)).catch(() => { /* the panel reports a conversation it cannot restore */ });
    };
    follow();
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);

  // Bots (owner only): the sidebar lists them; #agent is the default bot's line, #bot/<id> another's.
  const botList = useBots(personal);
  // A background answer finished: refresh the list so its last line and unread count are current.
  const unseenCount = lineStatus.unseen.length, reloadBotsRef = useRef(botList.reload); reloadBotsRef.current = botList.reload;
  useEffect(() => { if (unseenCount) void reloadBotsRef.current(); }, [unseenCount]);
  const [botId, setBotId] = useState(() => botFromHash(window.location.hash));
  const [newBotOpen, setNewBotOpen] = useState(false);
  useEffect(() => { const read = () => setBotId(botFromHash(window.location.hash)); window.addEventListener("hashchange", read); return () => window.removeEventListener("hashchange", read); }, []);
  const activeBot: Bot | null = !personal ? null : activeSection === "bot" ? botList.bots.find(b => b.id === botId) ?? null : activeSection === "agent" && !pastConversation ? botList.defaultBot : null;
  // Opening a bot's line marks its posted briefs read once, then the list refreshes so the badge clears.
  const openedBotId = activeBot?.id ?? null, reloadBots = botList.reload;
  useEffect(() => { if (openedBotId) void markBotRead(openedBotId).then(() => reloadBots()).catch(() => { /* the badge stays until the next refresh */ }); }, [openedBotId, reloadBots]);
  function openBot(bot: Bot) { setPastConversation(false); if (bot.is_default) navigate("agent"); else { window.location.hash = `bot/${bot.id}`; setActiveSection("bot"); setBotId(bot.id); } }

  function navigate(section: WorkspaceSection) {
    if (section === "agent") setPastConversation(false);
    if (section === activeSection) {
      if (section === "evidence" && window.location.hash !== "#evidence") window.location.hash = "evidence";
      // From one forecast's page, the 预测 tab goes back to the forecast home.
      if (section === "forecast" && window.location.hash !== "#forecast") window.location.hash = "forecast";
      return;
    }
    window.location.hash = section;
    setActiveSection(section);
  }

  function openStock(ticker: SupportedSymbol, section: WorkspaceSection = "overview") {
    if (ticker === requestedSymbol) setRetryKey((value) => value + 1);
    else setRequestedSymbol(ticker);
    navigate(section);
  }

  useEffect(() => {
    const controller = new AbortController();
    const version = ++requestVersion.current;
    setActiveData({ kind: "loading", symbol: requestedSymbol });
    Promise.allSettled([
      getFilingInventory(requestedSymbol, controller.signal),
      getV2Prices(requestedSymbol, controller.signal),
    ]).then(([filingResult, pricesResult]) => {
      if (controller.signal.aborted || version !== requestVersion.current) return;
      const nextFilings: FilingState = filingResult.status === "fulfilled"
        ? { kind: "ready", data: filingResult.value }
        : { kind: "error", message: actionMessage(filingResult.reason, "暂时无法读取官方申报清单。") };
      const priceHistory = pricesResult.status === "fulfilled" ? pricesResult.value.price_history : null;
      const priceError = pricesResult.status === "rejected" ? actionMessage(pricesResult.reason, "行情暂不可用。") : null;
      setActiveData({ kind: "ready", symbol: requestedSymbol, filings: nextFilings, priceHistory, priceError });
    });
    return () => controller.abort();
  }, [requestedSymbol, retryKey]);

  function addWatchSymbol() { const ticker = normalizeTicker(watchInput); if (!ticker) { setWatchError("请输入有效的美股代码，例如 AMD 或 BRK.B。"); return; } if (symbols.includes(ticker)) { setWatchError("该代码已在关注列表中。"); return; } if (symbols.length >= MAX_WATCHLIST) { setWatchError("关注列表最多保存 30 个代码。"); return; } setSymbols(items => [...items, ticker]); setWatchInput(""); setWatchError(""); openStock(ticker); }
  function removeWatchSymbol(ticker: string) { const remaining = symbols.filter(item => item !== ticker); setSymbols(remaining); setRequestedSymbol(current => selectionForWatchlist(current, remaining)); }
  const botRail = personal ? (close: () => void) => <BotRailList bots={botList.bots} routinesActive={activeSection === "routines"} onRoutines={() => { close(); navigate("routines"); }} portfolioActive={activeSection === "portfolio"} onPortfolio={() => { close(); navigate("portfolio"); }} forecastActive={navGroup(activeSection) === "forecast"} onForecast={() => { close(); navigate("forecast"); }} newsActive={activeSection === "news"} onNews={() => { close(); navigate("news"); }} error={botList.error} activeBotId={activeBot?.id ?? null} lineStatus={lineStatus} onOpen={bot => { close(); openBot(bot); }} onNew={() => { close(); setNewBotOpen(true); }} /> : undefined;
  const newBotDialog = newBotOpen && <NewBotDialog onClose={() => setNewBotOpen(false)} onCreated={bot => { setNewBotOpen(false); void botList.reload().then(() => openBot(bot)); }} />;
  const shellProps = { activeSection, navigate, symbol: requestedSymbol, symbols, onSelectStock: openStock, watchInput, setWatchInput, addWatchSymbol, watchError, setWatchError, onModeChange, botRail, overlay: newBotDialog };
  if (activeBot) return <Shell {...shellProps}><BotPage bot={activeBot} symbol={requestedSymbol} watchlist={symbols} onSelectSymbol={setRequestedSymbol} onOpenCompany={(ticker, section) => { const clean = normalizeTicker(ticker); if (clean) { if (!symbols.includes(clean) && symbols.length < MAX_WATCHLIST) setSymbols(items => [...items, clean]); openStock(clean, section === "forecast" ? "forecast" : "overview"); } }} onChanged={() => void botList.reload()} onDeleted={() => { void botList.reload(); navigate("agent"); }} onSettings={() => navigate("admin")} onModeChange={onModeChange} /></Shell>;
  if (personal && activeSection === "agent" && !pastConversation && !botList.loaded) return <Shell {...shellProps}><main className="workspace"><p role="status">{translatePhrase("正在读取…")}</p></main></Shell>;
  if (activeSection === "bot") return <Shell {...shellProps}><main className="workspace"><p role="status">{botList.loaded ? translatePhrase("bot 不存在或已删除。") : translatePhrase("正在读取…")}</p></main></Shell>;
  if (activeSection === "agent") return <Shell {...shellProps}><AgentChatPanel onSettings={() => navigate("admin")} onModeChange={onModeChange} /></Shell>;
  if (activeSection === "admin") return <Shell {...shellProps}><AgentAdminPage onBack={() => navigate("agent")} /></Shell>;
  if (activeSection === "routines") return <Shell {...shellProps}><RoutinesPage bots={botList.bots} onNavigate={navigate} onChanged={() => void botList.reload()} /></Shell>;
  if (activeSection === "portfolio") return <Shell {...shellProps}><PortfolioPage /></Shell>;
  if (activeSection === "news") return <Shell {...shellProps}><NewsSourcesPage /></Shell>;
  if (activeSection === "skills") return <Shell {...shellProps}><SkillsPage /></Shell>;
  if (activeSection === "memory") return <Shell {...shellProps}><MemoryPage onNavigate={navigate} /></Shell>;
  if (activeSection === "me") return <Shell {...shellProps}><MePage onNavigate={navigate} /></Shell>;

  async function startFilingScan() {
    const scanSymbol = requestedSymbol;
    if (!isSupportedSymbol(scanSymbol)) throw new Error("SEC 扫描需要有效的美股代码。");
    const result = await scanOfficialFilings(scanSymbol);
    if (activeSymbolRef.current === scanSymbol) {
      setActiveData((previous) => previous.kind === "ready" && previous.symbol === scanSymbol ? { ...previous, filings: { kind: "ready", data: result } } : previous);
    }
    return result;
  }

  // One forecast: the company comes from the record itself, so nothing waits on the selected stock's data.
  // The forecast group: the home, one forecast, one earnings judgment, the monitor.  None of them waits on the selected stock.
  if (activeSection === "forecast") {
    const goHome = () => { window.location.hash = "forecast"; };
    return <Shell {...shellProps}><main className="workspace"><SectionTabs section={activeSection} navigate={navigate} />
      {forecastRoute.view === "forecast" && forecastRoute.rootId ? <ForecastPage key={`${forecastRoute.rootId}:${forecastRoute.versionId ?? ""}:${forecastRoute.reviseSourceId ?? ""}`} rootId={forecastRoute.rootId} versionId={forecastRoute.versionId} reviseSourceId={forecastRoute.reviseSourceId} onHome={goHome} />
        : forecastRoute.view === "judgment" && forecastRoute.judgmentId ? <EarningsJudgmentPage key={forecastRoute.judgmentId} judgmentId={forecastRoute.judgmentId} onHome={goHome} />
        : forecastRoute.view === "monitor" ? <ForecastMonitorPage onHome={goHome} />
        : <ForecastHome queue={symbols} personal={personal} symbolFilter={forecastRoute.symbol} onClearSymbol={goHome} />}
    </main></Shell>;
  }
  // #revisions: the version section of the selected stock's latest forecast, or the forecast home when it has none.
  if (activeSection === "revisions") return <Shell {...shellProps}><main className="workspace"><SectionTabs section={activeSection} navigate={navigate} /><LatestForecastVersions key={requestedSymbol} symbol={requestedSymbol} onNone={() => navigate("forecast")} onHome={() => navigate("forecast")} /></main></Shell>;
  if (activeSection === "materials") return <Shell {...shellProps}><SectionTabs section={activeSection} navigate={navigate} /><MaterialLibrary key={`${requestedSymbol}:${materialFocusKey}`} symbol={requestedSymbol} onScan={async () => { const result = await startFilingScan(); setRetryKey((value) => value + 1); return result; }} /></Shell>;
  if (!symbols.length) return <Shell {...shellProps}><main className="workspace"><section className="empty-watchlist"><h1>{translatePhrase("关注列表为空")}</h1><p>{translatePhrase("添加一只股票，或恢复默认关注股票，继续查看研究总览。")}</p><button className="primary-action" onClick={() => { setSymbols(DEFAULT_SYMBOLS); setRequestedSymbol(DEFAULT_SYMBOL); }}>{translatePhrase("恢复默认股票")}</button></section></main></Shell>;
  if (activeData.kind === "loading" || activeData.symbol !== requestedSymbol) return <Shell {...shellProps}><Loading symbol={requestedSymbol} /></Shell>;
  const supported = isSupportedSymbol(requestedSymbol);
  return <Shell {...shellProps}>
    <main className="workspace" aria-labelledby="workspace-title">
      <WorkspacePageHeader symbol={requestedSymbol} section={activeSection as ResearchSection} recordCount={null} supported={supported} />
      <SectionTabs section={activeSection} navigate={navigate} />
      {activeSection === "overview" && <CurrentOverviewWorkspace symbols={symbols} personal={personal} onRemove={removeWatchSymbol} symbol={requestedSymbol} currentFilings={activeData.filings} priceHistory={activeData.priceHistory} priceError={activeData.priceError} onNavigate={navigate} onOpenStock={openStock} onPricesInitialized={() => setRetryKey(value => value + 1)} />}
      {activeSection === "evidence" && <EvidenceCenter key={requestedSymbol} symbol={requestedSymbol} supported={supported} onOpenForecast={() => navigate("forecast")} />}
      {activeSection === "evaluation" && <ModelScoresPage />}
      {activeSection === "replay" && <HistoricalReplayWorkspace key={requestedSymbol} initialSymbol={requestedSymbol} symbols={symbols} />}
    </main>
  </Shell>;
}

/** A bot's page: its one line in the middle, 工作区 / 档案 on the right.  Its turns go out with only its id. */
function BotPage({ bot, symbol, watchlist, onSelectSymbol, onOpenCompany, onChanged, onDeleted, onSettings, onModeChange }: { bot: Bot; symbol: string; watchlist: string[]; onSelectSymbol: (symbol: string) => void; onOpenCompany: (ticker: string, section?: "overview" | "forecast") => void; onChanged: () => void; onDeleted: () => void; onSettings: () => void; onModeChange: (mode: "guest" | "personal") => void }) {
  const selectBot = useSelectBot();
  useEffect(() => { void selectBot(bot); }, [bot]); // eslint-disable-line react-hooks/exhaustive-deps
  return <AgentChatPanel bot={bot} onSettings={onSettings} onModeChange={onModeChange} onTurnSettled={onChanged} onBotChanged={onChanged} side={<BotSide key={bot.id} bot={bot} symbol={symbol} watchlist={watchlist} onSelectSymbol={onSelectSymbol} onOpenCompany={onOpenCompany} onChanged={onChanged} onDeleted={onDeleted} />} />;
}

/** #revisions: the version section of the selected stock's latest forecast; no forecast sends the reader home. */
function LatestForecastVersions({ symbol, onNone, onHome }: { symbol: string; onNone: () => void; onHome: () => void }) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "ready"; rootId: string | null } | { kind: "error" }>({ kind: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    getV2ForecastRoots(symbol, controller.signal)
      .then((roots) => { if (!controller.signal.aborted) setState({ kind: "ready", rootId: roots.roots[0]?.id ?? null }); })
      .catch(() => { if (!controller.signal.aborted) setState({ kind: "error" }); });
    return () => controller.abort();
  }, [symbol]);
  const noForecast = state.kind === "ready" && state.rootId === null;
  useEffect(() => { if (noForecast) onNone(); }, [noForecast]); // eslint-disable-line react-hooks/exhaustive-deps
  if (state.kind === "loading") return <p role="status">{translatePhrase("正在读取…")}</p>;
  if (state.kind === "error") return <p className="v2-notice error" role="alert">{translatePhrase("暂时无法读取预测日期列表。")} <button className="text-button" type="button" onClick={onHome}>{translatePhrase("回到预测首页")}</button></p>;
  if (state.rootId === null) return null;
  return <ForecastPage key={state.rootId} rootId={state.rootId} focusVersions onHome={onHome} />;
}

function CurrentOverviewWorkspace({ symbols, personal, onRemove, symbol, currentFilings, priceHistory, priceError, onNavigate, onOpenStock, onPricesInitialized }: { symbols: string[]; personal: boolean; onRemove: (ticker: string) => void; symbol: string; currentFilings: FilingState; priceHistory: PriceHistory | null; priceError: string | null; onNavigate: (section: WorkspaceSection) => void; onOpenStock: (ticker: SupportedSymbol) => void; onPricesInitialized: () => void }) {
  const { t } = useLocale();
  // One forecast list feeds every queue card (no per-stock fan-out); materials and SEC counts belong to the current stock only.
  const [list, setList] = useState<{ kind: "loading" } | { kind: "ready"; data: V2ForecastList } | { kind: "error" }>({ kind: "loading" });
  const [lane, setLane] = useState<JudgmentLane<EarningsJudgment> | null>(null);
  const [materialCount, setMaterialCount] = useState<number | null>(null);
  const [monitor, setMonitor] = useState<{ kind: "loading" } | { kind: "ready"; data: Awaited<ReturnType<typeof getV2MonitorStatus>> } | { kind: "error" }>({ kind: "loading" });
  const [priceSeedState, setPriceSeedState] = useState("");
  async function initializePrices() { if (priceSeedState === "正在初始化行情…") return; setPriceSeedState("正在初始化行情…"); try { const result = await initializeMarketData(symbol); setPriceSeedState(result.inserted_count ? "行情初始化成功，新增行情已自动刷新。" : "初始化完成，但供应商没有返回可保存的行情。"); onPricesInitialized(); } catch (error) { setPriceSeedState(actionMessage(error, "行情初始化失败，请登录个人账户后重试。")); } }
  useEffect(() => {
    const controller = new AbortController();
    setMonitor({ kind: "loading" });
    setList({ kind: "loading" });
    setMaterialCount(null);
    getV2Forecasts({ symbols: symbols.slice(0, MAX_WATCHLIST), limit: 200 }, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setList({ kind: "ready", data }); })
      .catch(() => { if (!controller.signal.aborted) setList({ kind: "error" }); });
    getMaterialLibrary(symbol, { limit: 1, signal: controller.signal })
      .then((library) => { if (!controller.signal.aborted) setMaterialCount(library.total); })
      .catch(() => { /* the count stays a dash */ });
    if (personal) Promise.allSettled([getEarningsJudgments({ limit: 100 }, controller.signal)]).then(([result]) => { if (!controller.signal.aborted) setLane(judgmentLane(result)); });
    else setLane({ lane: "hidden" });
    getV2MonitorStatus(controller.signal).then((data) => { if (!controller.signal.aborted) setMonitor({ kind: "ready", data }); }).catch(() => { if (!controller.signal.aborted) setMonitor({ kind: "error" }); });
    return () => controller.abort();
  }, [symbol, symbols.join(","), personal]);
  const bySymbol = forecastBySymbol(list.kind === "ready" ? list.data.forecasts : []);
  const currentRows = bySymbol.get(symbol.toUpperCase()) ?? [];
  const currentWorkspaceState = list.kind;
  const currentVersion = currentWorkspaceState === "ready" ? currentRows[0] ?? null : null;
  const currentJobs = list.kind === "ready" ? list.data.job_alerts.filter((alert) => alert.symbol === symbol && (alert.status === "queued" || alert.status === "running")).length : 0;
  const currentRecord = researchRecord(symbol, list.kind === "ready" ? list.data.forecasts : [], lane?.lane === "ready" ? lane.judgments : []);
  // 打开预测 goes to the forecast itself; with none, to the home filtered to this stock, where it can be created.
  const openForecast = () => { window.location.hash = currentVersion ? `forecast/${currentVersion.id}` : `forecast?symbol=${encodeURIComponent(symbol)}`; };
  const currentFilingsList = currentFilings.kind === "ready" ? currentFilings.data.filings : [];
  const officialFilingCount = currentFilings.kind === "ready" ? currentFilingsList.length : null;
  return <section className="workspace-stack overview-workspace">
    <WorkspaceIntro eyebrow={t("研究总览")} title={t("从你的研究队列开始")} description={t("队列汇总独立预测、官方资料和已保存材料。没有预测时仍可上传材料、读取 SEC 原文并开始新研究。")} />
    <section className="overview-focus" aria-label={`${symbol} ${t("当前研究状态")}`}>
      <div><p className="eyebrow">{t("当前股票")} / {symbol}</p><h2>{currentWorkspaceState === "loading" ? t("正在读取研究状态") : currentWorkspaceState === "error" ? t("研究状态暂不可用") : currentVersion ? `${t("预测版本")} ${currentVersion.latest_version_no}` : t("可开始一项新研究")}</h2><p>{currentWorkspaceState === "loading" ? t("正在读取当前预测与研究记录。") : currentWorkspaceState === "error" ? t("当前预测状态读取失败，请稍后重试。") : currentVersion ? `${t("最近决策时间")} ${formatUtc(currentVersion.decision_at)}; ${t("决策模型")} ${currentVersion.decider.actual_model ?? t("未记录")}${currentVersion.target_end_date ? `; ${t("目标日")} ${currentVersion.target_end_date}` : ""}` : t("目前没有当前预测版本。历史行情与材料仍可查看，也可以直接创建预测。")}</p>
        {currentRecord.judgment && <p><a href={currentRecord.judgment.hash}>{t(currentRecord.judgment.typeLabel)}</a> · {t(currentRecord.judgment.direction)} · {t(currentRecord.judgment.result)}</p>}
        {currentVersion?.probabilities && <p className="fine-print">{t("概率未经校准，属实验性信息。仅供参考，买不买由你决定。")}</p>}</div>
      <div className="overview-focus-actions"><button className="primary-action" disabled={currentWorkspaceState === "loading"} onClick={openForecast}>{currentWorkspaceState === "loading" ? t("正在读取…") : currentVersion ? t("打开预测") : currentWorkspaceState === "ready" ? t("创建预测") : t("打开预测")}</button><button className="secondary-action" onClick={() => onNavigate("materials")}>{<Tx text={"查看材料库"} />}</button></div>
    </section>
    <section className="overview-metrics" aria-label={t("当前研究状态")}>
      <article><span>{<Tx text={"独立预测数"} />}</span><strong>{list.kind === "ready" ? currentRows.length : "—"}</strong><small>{currentJobs ? `${currentJobs} ${t("项任务处理中")}` : t("按当前预测记录统计")}</small></article>
      <article><span>{<Tx text={"材料总数"} />}</span><strong>{materialCount ?? "—"}</strong><small>{<Tx text={"已保存官方和上传材料"} />}</small></article>
      <article><span>{<Tx text={"SEC 官方材料"} />}</span><strong>{officialFilingCount ?? "—"}</strong><small>{currentFilings.kind === "error" ? t("官方资料目录暂不可用") : t("当前股票已保存的官方文件")}</small></article>
      <article><span>{<Tx text={"监控状态"} />}</span><strong>{monitor.kind === "loading" ? t("正在读取") : monitor.kind === "error" ? t("暂不可用") : t(monitorHealthLabel(monitor.data.health))}</strong><small>{monitor.kind === "loading" ? t("正在读取监控记录") : monitor.kind === "error" ? t("无法读取监控状态") : monitor.data.last_success?.completed_at ? `${t("最近成功")} ${formatUtc(monitor.data.last_success.completed_at)}` : t("尚无成功运行记录")}</small></article>
    </section>
    <section className="universe-section" aria-labelledby="universe-title"><div className="section-heading"><div><p className="eyebrow">{<Tx text={"研究队列"} />}</p><h2 id="universe-title">{<Tx text={"自选股票"} />}</h2></div><span>{<Tx text={"按当前研究数据读取"} />}</span></div><div className="universe-grid">
      {symbols.map((ticker) => {
        const tickerRows = bySymbol.get(ticker.toUpperCase()) ?? [];
        const latest = tickerRows[0] ?? null;
        const isCurrent = ticker === symbol;
        return <article className={`universe-card ${isCurrent ? "is-current" : ""}`} key={ticker}>
          <div className="universe-card-top"><strong>{ticker}</strong>{isCurrent && <span>{<Tx text={"当前"} />}</span>}</div>
          {list.kind === "loading" && <p className="universe-pending">{<Tx text={"正在读取研究状态…"} />}</p>}
          {list.kind === "error" && <p className="universe-error" role="status">{t("暂时无法读取该股票的研究状态。")}</p>}
          {list.kind === "ready" && <><dl><div><dt>{<Tx text={"独立预测"} />}</dt><dd>{tickerRows.length}</dd></div>{isCurrent && <><div><dt>{<Tx text={"材料"} />}</dt><dd>{materialCount ?? "—"}</dd></div><div><dt>{<Tx text={"SEC 官方材料"} />}</dt><dd>{officialFilingCount ?? "—"}</dd></div></>}</dl>
            {latest
              ? <small><a href={`#forecast/${latest.id}`}>{t("最新版本")} {latest.latest_version_no}</a> · {latest.probabilities ? `${t("下跌")} ${Math.round(latest.probabilities.bearish * 100)}% · ${t("持平")} ${Math.round(latest.probabilities.neutral * 100)}% · ${t("上涨")} ${Math.round(latest.probabilities.bullish * 100)}%` : t(modelStatusLabel(latest.model_status))} · {t("决策模型")} {latest.decider.actual_model ?? t("未记录")}{latest.target_end_date ? ` · ${t("目标日")} ${latest.target_end_date}` : ""}</small>
              : <small>{t("当前没有预测版本")}</small>}</>}
          <div className="watch-card-actions"><button className="universe-open" type="button" onClick={() => onOpenStock(ticker)}>{t("打开")} {ticker} {t("总览")} <span aria-hidden="true">→</span></button><button className="watch-remove" type="button" onClick={() => onRemove(ticker)} aria-label={`${t("从关注列表移除")} ${ticker}`}>×</button></div>
        </article>;
      })}
    </div></section>
    <div className="overview-shortcuts"><button className="text-button" onClick={() => onNavigate("materials")}>{<Tx text={"管理材料 / 扫描 SEC"} />}</button><button className="text-button" onClick={() => onNavigate("evaluation")}>{<Tx text={"查看到期评估"} />}</button><span>{priceError ? `${t("行情暂不可用")}: ${priceError}` : priceHistory?.latest_trading_date ? `${symbol} ${t("行情截至")} ${priceHistory.latest_trading_date}` : t("本地没有可展示的行情")}</span><button className="text-button" type="button" onClick={initializePrices} disabled={priceSeedState === "正在初始化行情…"}>{t("初始化一年行情")}</button>{priceSeedState && <small role="status">{t(priceSeedState)}</small>}</div>
  </section>;
}

function WorkspacePageHeader({ symbol, section, recordCount, supported }: { symbol: string; section: ResearchSection; recordCount: number | null; supported: boolean }) {
  const { t } = useLocale();
  const title = t(WORKSPACE_SECTION_TITLE[section]);
  return <header className="workspace-heading">
    <div><p className="eyebrow">{symbol} / {title}</p><h1 id="workspace-title">{title}</h1></div>
    <div className="workspace-context"><span className={`live-dot ${supported ? "" : "muted"}`} aria-hidden="true" /><span>{supported ? t("支持新建研究") : t("可查看已有研究")}</span>{recordCount !== null && <span className="workspace-record-count">{recordCount} {t("项独立预测")}</span>}</div>
  </header>;
}

function WorkspaceIntro({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  const { t } = useLocale();
  return <section className="workspace-intro">
    <div><p className="eyebrow">{t(eyebrow)}</p><h2>{t(title)}</h2><p>{t(description)}</p></div>
    {action && <div className="workspace-intro-action">{action}</div>}
  </section>;
}

type NavItem = { id: WorkspaceSection; group: NavGroup; label: string; hint: string; icon: string };

/** 「更多」: the six secondary destinations.  The trigger stays highlighted, and its subtitle names the open section. */
function MoreMenu({ items, activeGroup, onPick, placement, drop = "up" }: { items: NavItem[]; activeGroup: NavGroup; onPick: (section: WorkspaceSection) => void; placement: "rail" | "sheet"; drop?: "up" | "down" }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const active = items.find(item => item.group === activeGroup) ?? null;
  const menuId = placement === "rail" ? "rail-more-menu" : "more-sheet";
  useEffect(() => { setOpen(false); }, [activeGroup]);
  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    };
    const onPointer = (event: PointerEvent) => {
      if (placement === "sheet" || rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, placement]);
  function pick(id: WorkspaceSection) { setOpen(false); onPick(id); }
  const trigger = <button ref={triggerRef} type="button" className={active ? (placement === "sheet" ? "is-active" : "active") : ""} aria-current={active && !open ? "page" : undefined} aria-expanded={open} aria-haspopup="menu" aria-controls={menuId} onClick={() => setOpen(value => !value)}>
    <span aria-hidden="true">⋯</span>{placement === "sheet" ? t("更多") : <span><strong>{t("更多")}</strong><small>{active ? active.label : t("公司、预测与其它")}</small></span>}
  </button>;
  const menu = <div ref={menuRef} id={menuId} className={placement === "rail" ? `nav-more-menu${drop === "down" ? " is-down" : ""}` : "more-sheet"} role="menu" aria-label={t("更多")}>
    {items.map(item => {
      const current = item.group === activeGroup;
      return <button key={item.id} type="button" role="menuitem" className={current ? "active" : ""} aria-current={current ? "page" : undefined} onClick={() => pick(item.id)}><span aria-hidden="true">{item.icon}</span><span><strong>{item.label}</strong><small>{item.hint}</small></span></button>;
    })}
  </div>;
  if (placement === "sheet") return <div className="mobile-more">{trigger}{open && <div className="more-sheet-backdrop" onClick={() => setOpen(false)}><div onClick={event => event.stopPropagation()}>{menu}</div></div>}</div>;
  return <div className="nav-more" ref={rootRef}>{trigger}{open && menu}</div>;
}

function Shell({ activeSection, navigate, symbol, symbols, onSelectStock, watchInput, setWatchInput, addWatchSymbol, watchError, setWatchError, onModeChange, botRail, overlay, children }: { activeSection: WorkspaceSection; navigate: (section: WorkspaceSection) => void; symbol: string; symbols: string[]; onSelectStock: (ticker: SupportedSymbol) => void; watchInput: string; setWatchInput: (value: string) => void; addWatchSymbol: () => void; watchError: string; setWatchError: (value: string) => void; onModeChange:(mode:"guest"|"personal")=>void; botRail?: (close: () => void) => ReactNode; overlay?: ReactNode; children: ReactNode }) {
  const { t } = useLocale();
  const navRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [menuOpen,setMenuOpen]=useState(false),[pinned,setPinned]=useState(()=>localStorage.getItem("market-evidence-agent:nav-pinned:v1")==="1");
  const [isNarrow,setIsNarrow]=useState(()=>window.matchMedia("(max-width: 760px)").matches);
  const effectivePinned=pinned&&!isNarrow;
  const [ownerDialog,setOwnerDialog]=useState(false),[ownerInput,setOwnerInput]=useState(""),[ownerError,setOwnerError]=useState(""),[ownerBusy,setOwnerBusy]=useState(false);
  const ownerDialogRef=useRef<HTMLElement>(null),ownerInputRef=useRef<HTMLInputElement>(null),ownerReturnFocus=useRef<HTMLElement|null>(null);
  useEffect(()=>{if(!ownerDialog)return;ownerReturnFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;const background=Array.from(document.querySelectorAll<HTMLElement>(".app-frame > :not(.app-content), .app-content > :not(.owner-auth-backdrop)"));const prior=background.map(el=>el.inert);background.forEach(el=>{el.inert=true});ownerInputRef.current?.focus();const trap=(event:KeyboardEvent)=>{if(event.key!=="Tab")return;const items=ownerDialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),[href],select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])');if(!items?.length)return;const first=items[0],last=items[items.length-1];if(event.shiftKey&&(document.activeElement===first||!ownerDialogRef.current?.contains(document.activeElement))){event.preventDefault();last.focus()}else if(!event.shiftKey&&(document.activeElement===last||!ownerDialogRef.current?.contains(document.activeElement))){event.preventDefault();first.focus()}};document.addEventListener("keydown",trap,true);return()=>{document.removeEventListener("keydown",trap,true);background.forEach((el,i)=>{el.inert=prior[i]});ownerReturnFocus.current?.focus()}},[ownerDialog]);
  const menuRegion=useRef<HTMLDivElement>(null);
  const unpin=()=>{setPinned(false);localStorage.removeItem("market-evidence-agent:nav-pinned:v1");setMenuOpen(false)};
  useEffect(()=>{const media=window.matchMedia("(max-width: 760px)"),change=()=>setIsNarrow(media.matches);change();media.addEventListener("change",change);return()=>media.removeEventListener("change",change)},[]);
  useEffect(()=>{const insideNav=(node:EventTarget|null)=>Boolean(menuRegion.current?.contains(node as Node)||triggerRef.current?.contains(node as Node));const key=(e:KeyboardEvent)=>{if(e.key!=="Escape")return;if(ownerDialog){setOwnerDialog(false);return}if(!menuOpen&&!pinned)return;if(isNarrow||!pinned)setMenuOpen(false);else unpin();window.requestAnimationFrame(()=>triggerRef.current?.focus())};const outside=(e:PointerEvent)=>{if((isNarrow||!pinned)&&!insideNav(e.target))setMenuOpen(false)};const auth=()=>{setOwnerInput("");setOwnerError("");setOwnerDialog(true)};document.addEventListener("keydown",key);document.addEventListener("pointerdown",outside);window.addEventListener("owner-auth-required",auth);return()=>{document.removeEventListener("keydown",key);document.removeEventListener("pointerdown",outside);window.removeEventListener("owner-auth-required",auth)}},[pinned,isNarrow,ownerDialog,menuOpen]);
  const drawerNavigate=(section:WorkspaceSection)=>{if(isNarrow||!pinned)setMenuOpen(false);navigate(section)};
  const navFocusRequested=useRef(false);
  const focusFirstNavItem=()=>{navFocusRequested.current=true};
  useEffect(()=>{if(!navFocusRequested.current||!(menuOpen||effectivePinned))return;navFocusRequested.current=false;navRef.current?.querySelector<HTMLButtonElement>("button")?.focus()},[menuOpen,effectivePinned]);
  const closeNavDrawer=()=>{if(isNarrow||!pinned)setMenuOpen(false);else unpin();window.requestAnimationFrame(()=>triggerRef.current?.focus())};
  const toggleNavDrawer=()=>{if(isNarrow){setMenuOpen(open=>{const next=!open;if(next)focusFirstNavItem();return next});return}if(pinned){unpin();window.requestAnimationFrame(()=>triggerRef.current?.focus());return}setPinned(true);localStorage.setItem("market-evidence-agent:nav-pinned:v1","1");setMenuOpen(true);focusFirstNavItem()};
  useEffect(() => {
    if (activeSection === "admin") return;
    const navElement = navRef.current;
    const activeItem = navElement?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!navElement || !activeItem) return;
    const navRect = navElement.getBoundingClientRect();
    const itemRect = activeItem.getBoundingClientRect();
    if (itemRect.left < navRect.left) navElement.scrollLeft -= navRect.left - itemRect.left;
    else if (itemRect.right > navRect.right) navElement.scrollLeft += itemRect.right - navRect.right;
  }, [activeSection]);
  const moreItems: NavItem[] = [
    { id: "overview", group: "company", label: t("公司"), hint: t("研究总览"), icon: "◌" },
    { id: "forecast", group: "forecast", label: t("预测"), hint: t("预测、修订与回放"), icon: "◔" },
    { id: "materials", group: "library", label: t("资料库"), hint: t("证据与材料"), icon: "▤" },
    { id: "skills", group: "skills", label: t("技能"), hint: t("做事的步骤"), icon: "⌁" },
    { id: "memory", group: "memory", label: t("记忆"), hint: t("画像和往事"), icon: "◇" },
    { id: "admin", group: "settings", label: t("设置"), hint: t("模型与账户"), icon: "⚙" },
  ];
  // On the desktop rail (owner only) 预测 is a bot-rail row of its own, so it leaves the 更多 menu there.
  // The mobile tab bar and guests, who have no rail row, keep it in 更多.
  const railMoreItems = botRail ? moreItems.filter(item => item.id !== "forecast") : moreItems;
  const mobileTabs: Array<{ id: WorkspaceSection; label: string; icon: React.ReactNode; active: boolean }> = [
    { id: "agent", label: t("对话"), icon: "✳", active: activeSection === "agent" || activeSection === "bot" },
    { id: "routines", label: t("例行任务"), icon: <RoutineIcon />, active: activeSection === "routines" },
    { id: "portfolio", label: t("持仓"), icon: <PortfolioIcon />, active: activeSection === "portfolio" },
  ];
  const research = isResearchSection(activeSection);
  // The forecast group takes its company from the record, so it has no stock picker.
  const stockPicker = research && navGroup(activeSection) !== "forecast";
  return <div className={`app-frame${effectivePinned?" is-nav-pinned":""}`}>
    <div className="nav-drawer-region" ref={menuRegion}>
      {isNarrow&&menuOpen&&<div className="nav-scrim" aria-hidden="true" onClick={()=>setMenuOpen(false)}/>}
      <aside id="workspace-navigation" className={`app-rail ${menuOpen||effectivePinned?"is-open":""}`} aria-label={t("主要导航")}>
        <button className="rail-nav-close" type="button" aria-label={t("收起导航")} aria-controls="workspace-navigation" onClick={closeNavDrawer}><span aria-hidden="true">×</span></button>
      <a className="workspace-brand" href="#agent" onClick={() => navigate("agent")} aria-label={`FinBot · ${t("对话")}`}><BrandLogo /><span>FinBot<br /><em>{t("理财助手")}</em></span></a>
      {botRail?.(() => { if (isNarrow || !pinned) setMenuOpen(false); })}
      <nav ref={navRef} className={`workspace-nav${botRail ? " is-bottom" : ""}`}>
        {!botRail && <button type="button" className={navGroup(activeSection) === "chat" ? "active" : ""} aria-current={navGroup(activeSection) === "chat" ? "page" : undefined} onClick={() => drawerNavigate("agent")}><span aria-hidden="true">✳</span><span><strong>{t("对话")}</strong><small>{t("首页")}</small></span></button>}
        <MoreMenu items={railMoreItems} activeGroup={navGroup(activeSection)} onPick={drawerNavigate} placement="rail" drop={botRail ? "up" : "down"} />
      </nav>
      <div className="rail-bottom">{research && <span><span className="rail-review-dot" aria-hidden="true" />{<Tx text={"判断可回到原始来源查看"} />}</span>}</div>
      </aside>
    </div>
    <div className="app-content">
      <header className="topbar">
        <div className="topbar-lead">
          <button ref={triggerRef} className="nav-menu-trigger" type="button" aria-label={t(isNarrow?(menuOpen?"收起导航":"打开导航菜单"):(pinned?"收起导航":"打开导航菜单"))} aria-expanded={isNarrow?menuOpen:menuOpen||effectivePinned} aria-controls="workspace-navigation" onClick={toggleNavDrawer}>☰</button>
          {stockPicker && <div className="topbar-path"><span>{<Tx text={"公司研究"} />}</span><b>/</b><strong>{symbol}</strong></div>}
        </div>
        <div className="toolbar-controls">
        {stockPicker && <div className="symbol-form">
          <label htmlFor="symbol">{<Tx text={"切换股票"} />}</label>
          <select id="symbol" value={symbol} onChange={(event) => onSelectStock(event.target.value as SupportedSymbol)} aria-label={t("切换股票")}>
            {!symbols.includes(symbol) && <option value={symbol}>{symbol} · {t("当前")}</option>}
            {symbols.map((ticker) => <option key={ticker} value={ticker}>{ticker}</option>)}
          </select>
        </div>}
        {stockPicker && <form className="watchlist-add" onSubmit={event => { event.preventDefault(); addWatchSymbol(); }}><label className="visually-hidden" htmlFor="watch-add">{t("添加股票")}</label><input id="watch-add" value={watchInput} onChange={event => { setWatchInput(event.target.value); setWatchError(""); }} placeholder={t("添加代码，如 AMD")} maxLength={10} /><button type="submit" aria-label={t("添加股票")}>+</button>{watchError && <span role="alert">{t(watchError)}</span>}</form>}
        </div>
      </header>
      {children}
      {overlay}
      {ownerDialog&&<div className="owner-auth-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setOwnerDialog(false)}}><section ref={ownerDialogRef} className="owner-auth-dialog" role="dialog" aria-modal="true" aria-labelledby="owner-auth-title"><button className="owner-auth-close" type="button" aria-label={t("关闭")} onClick={()=>setOwnerDialog(false)}>×</button><p className="eyebrow">{t("站点写入操作")}</p><h2 id="owner-auth-title">{t("请登录个人账户")}</h2><p>{t("登录后可继续进行站点操作。登录完成后，请手动重试刚才未完成的操作。")}</p><label>{t("个人登录密码或口令")}<input ref={ownerInputRef} type="password" value={ownerInput} autoComplete="current-password" onChange={e=>setOwnerInput(e.target.value)}/></label>{ownerError&&<p role="alert">{ownerError}</p>}<div><button className="primary-action" disabled={!ownerInput||ownerBusy} onClick={()=>{setOwnerBusy(true);void personalChatLogin(ownerInput).then(credential=>{completePersonalLogin(credential,setChatMode,onModeChange);setOwnerDialog(false);setOwnerInput("")}).catch(error=>setOwnerError(error instanceof Error?error.message:t("登录暂不可用。"))).finally(()=>setOwnerBusy(false))}}>{ownerBusy?t("正在登录…"):t("登录并授权")}</button><button className="secondary-action" onClick={()=>setOwnerDialog(false)}>{t("稍后")}</button></div></section></div>}
      <footer>{<Tx text={"FinBot · 本地研究记录 · 研究判断可追溯到原始来源"} />}</footer>
      <nav className="mobile-tabbar" aria-label={t("主要导航")}>
        {mobileTabs.map(tab => <button key={tab.id} type="button" aria-current={tab.active ? "page" : undefined} onClick={() => navigate(tab.id)}><span aria-hidden="true">{tab.icon}</span>{tab.label}</button>)}
        <MoreMenu items={moreItems} activeGroup={navGroup(activeSection)} onPick={navigate} placement="sheet" />
      </nav>
    </div>
  </div>;
}

function Loading({ symbol }: { symbol: string }) {
  const { t } = useLocale();
  return <main className="state-card" aria-live="polite" aria-busy="true"><span className="loading-mark" aria-hidden="true" /><p className="kicker">{<Tx text={"公司研究"} />}</p><h1>{t("正在读取")} {symbol} {t("的研究资料")}</h1><p>{<Tx text={"正在读取本地预测、SEC 目录和行情。"} />}</p></main>;
}

function SectionTabs({ section, navigate }: { section: WorkspaceSection; navigate: (section: WorkspaceSection) => void }) {
  const { t } = useLocale();
  const group = navGroup(section);
  const forecastTab = (FORECAST_TABS as readonly string[]).includes(section);
  const labels: Record<string, string> = { overview: "总览", forecast: "预测", revisions: "预测修订", evaluation: "模型成绩", replay: "历史回放", materials: "材料库", evidence: "证据" };
  const tab = (id: WorkspaceSection, active: boolean, label = labels[id]) => <button key={id} type="button" aria-current={active ? "page" : undefined} onClick={() => navigate(id)}>{t(label)}</button>;
  if (group === "library") return <nav className="section-tabs" aria-label={t("资料库")}>{LIBRARY_TABS.map(id => tab(id, section === id))}</nav>;
  if (group !== "company" && group !== "forecast") return null;
  return <>
    <nav className="section-tabs" aria-label={t("公司")}>{tab("overview", section === "overview")}{tab("forecast", forecastTab)}</nav>
    {forecastTab && <nav className="section-tabs is-secondary" aria-label={t("预测")}>{FORECAST_TAB_BUTTONS.map(id => tab(id, section === id || (id === "forecast" && section === "revisions")))}</nav>}
  </>;
}

function isSupportedSymbol(symbol: string): symbol is SupportedSymbol { return isValidSymbol(symbol); }
function isValidSymbol(symbol: string): boolean { return /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/i.test(symbol.trim()); }
function sectionFromHash(): WorkspaceSection {
  const value = window.location.hash.replace(/^#/, "").split(/[/?]/, 1)[0];
  if ((["overview", "forecast", "evidence", "materials", "revisions", "evaluation", "replay", "agent", "bot", "admin", "routines", "news", "skills", "memory", "me", "portfolio"] as const).includes(value as WorkspaceSection)) return value as WorkspaceSection;
  // The conversation is the home page.
  return HASH_ALIASES[value] ?? "agent";
}
function actionMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return translatePhrase(fallback);
  if (error.message.includes("SEC_EDGAR_USER_AGENT")) return translatePhrase("尚未配置 SEC 联系邮箱。请先按 README 配置后重试。");
  return translatePhrase(error.message);
}
function formatPrice(value: number) { return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value); }
function formatReturn(value: number) { return formatDelta(value, { scale: 100, suffix: "%" }); }
function formatPercent(value: number) { return `${(value * 100).toFixed(1)}%`; }
function monitorHealthLabel(status: string) {
  if (status === "healthy") return translatePhrase("监控正常");
  if (status === "delayed") return translatePhrase("监控延迟");
  if (status === "degraded") return translatePhrase("监控异常");
  return translatePhrase("尚无记录");
}
function signedPoints(value: number) { return formatDelta(value, { scale: 100, suffix: "pp" }); }
function probabilityLabel(key: "bearish" | "neutral" | "bullish") { return translatePhrase(({ bearish: "看跌", neutral: "中性", bullish: "看涨" })[key]); }
function formatDateTime(value: string, locale: "zh-CN" | "en-US" = getLocalePreference()) { return formatLocalizedDateTime(value, locale); }
function formatUtc(value: string) { return formatDateTime(value); }
