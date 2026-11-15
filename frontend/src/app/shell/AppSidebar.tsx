import { Link } from "react-router";
import { Suspense, lazy, useEffect, useRef, useState, type ComponentType } from "react";
import { CalendarClock, ChartLine, ChevronRight, ChevronsUpDown, Command, History, MessageSquare, Plus, Search, Settings, Sparkles, UserRound, Wallet } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupAction, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuAction, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem, SidebarMenuSub, SidebarMenuSubButton, SidebarMenuSubItem, SidebarRail, SidebarSeparator, SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import type { Bot } from "../../api/bots";
import { botSections } from "../../bot-items.mjs";
import { isWaiting } from "../../bot-marker.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { activeArea, activeItem, areaItems, areaPath, type Area } from "../../shell-nav.mjs";
import { openCommandMenu } from "@/components/command/command-events";
import { ThemeToggle, type ModeChange } from "./account";
import { BotRow } from "./BotRow";

// The two Radix menus are in their own chunk (menus.tsx); the sidebar draws plain buttons until it arrives.
const AccountMenuLazy = lazy(() => import("./menus").then(m => ({ default: m.AccountMenu })));
const CollapsedGroupMenuLazy = lazy(() => import("./menus").then(m => ({ default: m.CollapsedGroupMenu })));

export type ShellNavProps = {
  /** The current address (path and query). */
  path: string;
  personal: boolean;
  symbol: string;
  bots: Bot[];
  botsError: string;
  activeBotId: string | null;
  lineStatus: { running: string[]; unseen: string[]; waiting: string[] };
  /** The one to-do number (the 任务 entry carries it). */
  routinesCount: number;
  onNewBot: () => void;
  onModeChange: ModeChange;
};

const AREA_ICON: Record<Exclude<Area, "chat">, ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" }>> = { research: ChartLine, portfolio: Wallet, routines: CalendarClock, assistant: Sparkles, settings: Settings };
const AREA_LABEL: Record<Exclude<Area, "chat">, string> = { research: "研究", portfolio: "持仓", routines: "任务", assistant: "助手", settings: "设置" };

/** An area with sub-pages (研究, 助手, 设置).  Expanded: the sub-pages open under it while it is the area the reader is in (or when asked to).  Collapsed to the icon bar: the same pages in a menu beside it. */
function NavGroupItem({ area, props }: { area: "research" | "assistant" | "settings"; props: ShellNavProps }) {
  const { t } = useLocale();
  const { state } = useSidebar();
  const current = activeArea(props.path) === area;
  const item = current ? activeItem(props.path) : null;
  const [open, setOpen] = useState(current);
  const [wanted, setWanted] = useState(false);   // pressed before the menu chunk arrived: it opens when it does
  useEffect(() => { if (current) setOpen(true); }, [current]);
  const Icon = AREA_ICON[area];
  const items = areaItems(area, { personal: props.personal });
  const label = t(AREA_LABEL[area]);
  if (state === "collapsed") {
    const button = (onClick?: () => void) => <SidebarMenuButton isActive={current} tooltip={label} aria-label={label} aria-haspopup="menu" aria-expanded={false} onClick={onClick}><Icon aria-hidden="true" /><span>{label}</span></SidebarMenuButton>;
    return <SidebarMenuItem>
      <Suspense fallback={button(() => setWanted(true))}>
        <CollapsedGroupMenuLazy area={area} label={label} Icon={Icon} current={current} item={item} symbol={props.symbol} personal={props.personal} defaultOpen={wanted} />
      </Suspense>
    </SidebarMenuItem>;
  }
  return <SidebarMenuItem>
    <Collapsible open={open} onOpenChange={setOpen}>
      <SidebarMenuButton asChild isActive={current && !item}>
        <Link to={areaPath(area, props.symbol)} aria-current={current && !item ? "page" : undefined}><Icon aria-hidden="true" /><span>{label}</span></Link>
      </SidebarMenuButton>
      <CollapsibleTrigger asChild>
        <SidebarMenuAction aria-label={`${open ? t("收起") : t("展开")}${label}`} className="data-[state=open]:rotate-90"><ChevronRight aria-hidden="true" /></SidebarMenuAction>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <SidebarMenuSub>
          {items.map(sub => <SidebarMenuSubItem key={sub.id}>
            <SidebarMenuSubButton asChild isActive={item === sub.id}>
              <Link to={areaPath(area, props.symbol, sub.id)} aria-current={item === sub.id ? "page" : undefined}><span>{t(sub.label)}</span></Link>
            </SidebarMenuSubButton>
          </SidebarMenuSubItem>)}
        </SidebarMenuSub>
      </CollapsibleContent>
    </Collapsible>
  </SidebarMenuItem>;
}

/** An area that is one page (持仓, 任务). */
function NavLeaf({ area, props, badge = 0 }: { area: "portfolio" | "routines"; props: ShellNavProps; badge?: number }) {
  const { t } = useLocale();
  const { state } = useSidebar();
  const current = activeArea(props.path) === area;
  const Icon = AREA_ICON[area];
  const label = t(AREA_LABEL[area]);
  const spoken = badge > 0 ? `${label}，${badge} ${t("条待确认")}` : label;
  return <SidebarMenuItem>
    <SidebarMenuButton asChild isActive={current} tooltip={spoken}>
      <Link to={areaPath(area, props.symbol)} aria-current={current ? "page" : undefined} aria-label={spoken}><Icon aria-hidden="true" /><span>{label}</span></Link>
    </SidebarMenuButton>
    {badge > 0 && (state === "collapsed"
      ? <span aria-hidden="true" data-count="" className="pointer-events-none absolute top-0 right-0 grid min-w-4 place-items-center rounded-full bg-brand px-1 text-caption leading-4 text-primary-foreground ring-2 ring-sidebar">{badge > 99 ? "99+" : badge}</span>
      : <SidebarMenuBadge data-count="" aria-hidden="true" className="rounded-full bg-brand px-1.5 text-caption text-primary-foreground peer-hover/menu-button:text-primary-foreground peer-data-[active=true]/menu-button:text-primary-foreground">{badge > 99 ? "99+" : badge}</SidebarMenuBadge>)}
  </SidebarMenuItem>;
}

/** The 对话 section: the bots (owner) or the one plain chat (guest), the history entry and 新建 bot. */
function ChatSection({ props }: { props: ShellNavProps }) {
  const { t } = useLocale();
  const { state } = useSidebar();
  const { top, groups } = botSections(props.bots);
  const inChat = activeArea(props.path) === "chat";
  const historyActive = inChat && activeItem(props.path) === "history";
  const row = (bot: Bot) => <BotRow key={bot.id} bot={bot} active={bot.id === props.activeBotId}
    running={props.lineStatus.running.includes(`bot:${bot.id}`)} waiting={isWaiting(bot, props.lineStatus.waiting)} unseen={props.lineStatus.unseen.includes(`bot:${bot.id}`)} />;
  return <SidebarGroup>
    <SidebarGroupLabel>{t("对话")}</SidebarGroupLabel>
    <SidebarGroupAction asChild title={t("历史对话")}>
      <Link to={paths.chatHistory()} aria-label={t("历史对话")} aria-current={historyActive ? "page" : undefined} className={historyActive ? "bg-sidebar-accent" : undefined}><History aria-hidden="true" /></Link>
    </SidebarGroupAction>
    <SidebarMenu>
      {props.personal ? <>
        {props.botsError && <li role="alert" className="px-2 py-1 text-caption text-muted-foreground">{t(props.botsError)}</li>}
        {top && row(top)}
        {groups.map(group => <li key={group.name || "_"}>
          {group.name && state !== "collapsed" && <p className="px-2 pt-2 pb-0.5 text-caption text-muted-foreground">{group.name}</p>}
          <ul className="flex flex-col gap-1">{group.bots.map(bot => row(bot))}</ul>
        </li>)}
        <SidebarMenuItem>
          <SidebarMenuButton onClick={props.onNewBot} tooltip={t("新建 bot")} className="text-muted-foreground"><Plus aria-hidden="true" /><span>{t("新建 bot")}</span></SidebarMenuButton>
        </SidebarMenuItem>
      </> : <SidebarMenuItem>
        <SidebarMenuButton asChild isActive={inChat && !historyActive} tooltip={t("对话")}>
          <Link to={paths.chat()} aria-current={inChat && !historyActive ? "page" : undefined}><MessageSquare aria-hidden="true" /><span>{t("对话")}</span></Link>
        </SidebarMenuButton>
      </SidebarMenuItem>}
    </SidebarMenu>
  </SidebarGroup>;
}

/** the account menu (个人模式): the one place that shows the mode, switches it and signs out (design S5).  The menu is lazy: a button of the same look stands in until it arrives. */
function AccountMenu({ props }: { props: ShellNavProps }) {
  const { t } = useLocale();
  const [wanted, setWanted] = useState(false);   // pressed before the menu chunk arrived: it opens when it does
  const hadFocus = useRef(false);                 // the stand-in held focus when the real button replaced it: hand focus over
  const mode = props.personal ? t("个人模式") : t("访客只读");
  const standIn = <SidebarMenuButton size="lg" tooltip={mode} aria-haspopup="menu" aria-expanded={false} onFocus={() => { hadFocus.current = true; }} onBlur={() => { hadFocus.current = false; }} onClick={() => setWanted(true)}>
    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-sunken text-muted-foreground"><UserRound aria-hidden="true" className="size-4" /></span>
    <span className="min-w-0 flex-1 truncate">{mode}</span>
    <ChevronsUpDown aria-hidden="true" className="ml-auto size-4 text-muted-foreground" />
  </SidebarMenuButton>;
  return <Suspense fallback={standIn}><AccountMenuLazy personal={props.personal} onModeChange={props.onModeChange} defaultOpen={wanted} focusOnMount={hadFocus.current || wanted} /></Suspense>;
}

/** The platform's name for the palette shortcut: Cmd-K on a Mac, Ctrl K elsewhere (read once; the sidebar is only drawn on a desktop). */
const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** The button at the top of the sidebar that opens the command palette (design 4.1).  On the icon bar it shrinks to the icon. */
function PaletteButton() {
  const { t } = useLocale();
  const label = t("命令面板");
  return <button type="button" aria-label={label} aria-haspopup="dialog" aria-keyshortcuts="Control+K Meta+K" title={`${label} (${isMac ? "Cmd+K" : "Ctrl+K"})`}
    onClick={(event) => openCommandMenu(event.currentTarget)}
    className="inline-flex h-8 items-center gap-1.5 rounded-sm border border-line px-2 text-caption text-muted-foreground outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring group-data-[collapsible=icon]:w-8 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
    <Search aria-hidden="true" className="size-3.5" />
    <span aria-hidden="true" className="inline-flex items-center gap-0.5 group-data-[collapsible=icon]:hidden">{isMac ? <Command className="size-3" /> : "Ctrl"}<span>K</span></span>
  </button>;
}

/** The desktop sidebar (design 3.1): 对话 with the bots, then 研究 / 持仓 / 任务, then 助手 / 设置, and the account at the foot. */
export function AppSidebar({ props }: { props: ShellNavProps }) {
  const { t } = useLocale();
  return <Sidebar collapsible="icon" role="navigation" aria-label={t("主要导航")}>
    <SidebarHeader className="flex-row items-center gap-1 group-data-[collapsible=icon]:flex-col">
      <Link to={paths.chat()} aria-label={`FinBot · ${t("对话")}`} className="min-w-0 flex-1 truncate rounded-sm px-2 text-title-s font-semibold text-sidebar-foreground outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring group-data-[collapsible=icon]:hidden">FinBot</Link>
      <PaletteButton />
      <SidebarTrigger label={t("展开或收起导航")} />
    </SidebarHeader>
    <SidebarContent>
      <ChatSection props={props} />
      <SidebarSeparator />
      <SidebarGroup>
        <SidebarMenu>
          <NavGroupItem area="research" props={props} />
          {props.personal && <NavLeaf area="portfolio" props={props} />}
          {props.personal && <NavLeaf area="routines" props={props} badge={props.routinesCount} />}
        </SidebarMenu>
      </SidebarGroup>
      <SidebarSeparator />
      <SidebarGroup>
        <SidebarMenu>
          <NavGroupItem area="assistant" props={props} />
          <NavGroupItem area="settings" props={props} />
        </SidebarMenu>
      </SidebarGroup>
    </SidebarContent>
    <SidebarFooter>
      <div className="flex items-center gap-1 group-data-[collapsible=icon]:flex-col">
        <div className="min-w-0 flex-1"><SidebarMenu><SidebarMenuItem><AccountMenu props={props} /></SidebarMenuItem></SidebarMenu></div>
        <ThemeToggle />
      </div>
    </SidebarFooter>
    <SidebarRail label={t("展开或收起导航")} />
  </Sidebar>;
}
