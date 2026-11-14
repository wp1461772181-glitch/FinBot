import { Link } from "react-router";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { BrandLogo } from "./BotOrb";
import { RoutineIcon } from "./BotPages";
import { PortfolioIcon } from "./PortfolioIcon";
import { Tx, useLocale } from "./i18n";
import { personalChatLogin, setChatMode } from "./api";
import { completePersonalLogin } from "./chat-mode-switch.mjs";
import { paths } from "./routes.mjs";

// The old shell (moved out of App.tsx unchanged apart from its wiring): the rail, the 「更多」 menu, the mobile tab bar
// and the section tabs.  Clicks go through `navigate(section)`, which the workspace layout turns into a router jump;
// the highlight reads the section the current address belongs to.  P2.2 replaces all of it.
export type SupportedSymbol = string;
export type WorkspaceSection = "overview" | "forecast" | "evidence" | "materials" | "revisions" | "evaluation" | "replay" | "agent" | "bot" | "admin" | "routines" | "portfolio" | "news" | "skills" | "memory" | "me" | "knowledge";
export type ResearchSection = Exclude<WorkspaceSection, "agent" | "bot" | "admin" | "routines" | "portfolio" | "news" | "skills" | "memory" | "me" | "knowledge">;
// The personal-agent navigation groups the older sections: 公司 holds 总览; 预测 holds the forecast home, one
// forecast's page, 模型成绩 (#evaluation) and 历史回放, and #revisions opens the versions of a forecast; 资料库 holds
// 材料库 and 证据.  Those six (公司、预测、资料库、技能、记忆、设置) are one 「更多」 control on the mobile tab bar and
// for guests.  On the desktop rail an owner has 预测 as a row of its own and the other five in 「更多」.
// 例行任务 is not one of them: it is a bot-rail row (with 持仓, 预测 and 新闻源 beside it) and its own mobile tab, so
// it stays primary chrome.  The old names below are section names (what the highlight reads), no longer addresses: routes.mjs maps an address to one.
export type NavGroup = "chat" | "routines" | "portfolio" | "news" | "company" | "forecast" | "library" | "skills" | "memory" | "settings";
const FORECAST_TABS = ["forecast", "revisions", "evaluation", "replay"] as const;
// #revisions is still an address of the group, but it has no tab of its own: it is a part of one forecast's page.
const FORECAST_TAB_BUTTONS = ["forecast", "evaluation", "replay"] as const;
const LIBRARY_TABS = ["materials", "evidence"] as const;
export function navGroup(section: WorkspaceSection): NavGroup {
  if (section === "agent" || section === "bot") return "chat";
  if (section === "admin" || section === "knowledge") return "settings";
  if (section === "routines" || section === "portfolio" || section === "news" || section === "skills" || section === "memory") return section;
  if (section === "me") return "memory";
  if ((LIBRARY_TABS as readonly string[]).includes(section)) return "library";
  if ((FORECAST_TABS as readonly string[]).includes(section)) return "forecast";
  return "company";
}
export function isResearchSection(section: WorkspaceSection): section is ResearchSection { const group = navGroup(section); return group === "company" || group === "forecast" || group === "library"; }

export const WORKSPACE_SECTION_TITLE: Record<ResearchSection, string> = {
  overview: "研究总览", forecast: "预测", evidence: "证据中心", materials: "材料库", revisions: "预测修订", evaluation: "模型成绩", replay: "历史回放",
};

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

export function Shell({ activeSection, navigate, symbol, symbols, onSelectStock, watchInput, setWatchInput, addWatchSymbol, watchError, setWatchError, onModeChange, botRail, overlay, children }: { activeSection: WorkspaceSection; navigate: (section: WorkspaceSection) => void; symbol: string; symbols: string[]; onSelectStock: (ticker: SupportedSymbol) => void; watchInput: string; setWatchInput: (value: string) => void; addWatchSymbol: () => void; watchError: string; setWatchError: (value: string) => void; onModeChange:(mode:"guest"|"personal")=>void; botRail?: (close: () => void) => ReactNode; overlay?: ReactNode; children: ReactNode }) {
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
      <Link className="workspace-brand" to={paths.chat()} aria-label={`FinBot · ${t("对话")}`}><BrandLogo /><span>FinBot<br /><em>{t("理财助手")}</em></span></Link>
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

export function SectionTabs({ section, navigate }: { section: WorkspaceSection; navigate: (section: WorkspaceSection) => void }) {
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
