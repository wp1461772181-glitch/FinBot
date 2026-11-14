import { Link } from "react-router";
import { useEffect, useRef, type ComponentType } from "react";
import { ChevronsUpDown, Eye, KeyRound, LogOut, UserRound } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { SidebarMenuButton } from "@/components/ui/sidebar";
import { useLocale } from "../../i18n";
import { areaItems, areaPath, type Area } from "../../shell-nav.mjs";
import { useAccountActions, type ModeChange } from "./account";
import { openLoginDialog } from "./login-events";

// The sidebar's two Radix menus.  They live in their own chunk (Radix menu, collection, popper and floating-ui are
// about a third of the shell's weight) and are fetched right after the first paint: until then the sidebar shows
// a plain button with the same look (see AppSidebar).

/** the account menu (个人模式): the one place that shows the mode, switches it and signs out (design S5). */
export function AccountMenu({ personal, onModeChange, defaultOpen, focusOnMount }: { personal: boolean; onModeChange: ModeChange; defaultOpen: boolean; focusOnMount: boolean }) {
  const { t } = useLocale();
  const actions = useAccountActions(onModeChange);
  const mode = personal ? t("个人模式") : t("访客只读");
  const trigger = useRef<HTMLButtonElement>(null);
  // This button replaces a plain stand-in; if that one held focus, the keyboard user keeps their place.
  useEffect(() => { if (focusOnMount) trigger.current?.focus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <DropdownMenu defaultOpen={defaultOpen}>
    <DropdownMenuTrigger asChild>
      <SidebarMenuButton size="lg" tooltip={mode} className="data-[state=open]:bg-sidebar-accent" ref={trigger}>
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-sunken text-muted-foreground"><UserRound aria-hidden="true" className="size-4" /></span>
        <span className="min-w-0 flex-1 truncate">{mode}</span>
        <ChevronsUpDown aria-hidden="true" className="ml-auto size-4 text-muted-foreground" />
      </SidebarMenuButton>
    </DropdownMenuTrigger>
    <DropdownMenuContent side="top" align="start" className="w-(--radix-dropdown-menu-trigger-width) min-w-56">
      <DropdownMenuLabel className="text-caption text-muted-foreground">{t("当前")}：{mode}</DropdownMenuLabel>
      <DropdownMenuSeparator />
      {personal
        ? <DropdownMenuItem onSelect={actions.toGuest}><Eye aria-hidden="true" />{t("切换到访客只读")}</DropdownMenuItem>
        : <DropdownMenuItem onSelect={() => openLoginDialog(true)}><KeyRound aria-hidden="true" />{t("登录个人")}</DropdownMenuItem>}
      <DropdownMenuItem onSelect={actions.signOut}><LogOut aria-hidden="true" />{t("登出")}</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>;
}

type IconType = ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" }>;

/** An area with sub-pages, while the sidebar is collapsed to the icon bar: the same pages in a menu beside the icon. */
export function CollapsedGroupMenu({ area, label, Icon, current, item, symbol, personal, defaultOpen }: { area: Exclude<Area, "chat" | "portfolio" | "routines">; label: string; Icon: IconType; current: boolean; item: string | null; symbol: string; personal: boolean; defaultOpen: boolean }) {
  const { t } = useLocale();
  return <DropdownMenu defaultOpen={defaultOpen}>
    <DropdownMenuTrigger asChild>
      <SidebarMenuButton isActive={current} tooltip={label} aria-label={label}><Icon aria-hidden="true" /><span>{label}</span></SidebarMenuButton>
    </DropdownMenuTrigger>
    <DropdownMenuContent side="right" align="start" className="min-w-40">
      <DropdownMenuLabel>{label}</DropdownMenuLabel>
      {areaItems(area, { personal }).map(sub => <DropdownMenuItem key={sub.id} asChild>
        <Link to={areaPath(area, symbol, sub.id)} aria-current={item === sub.id ? "page" : undefined} className={item === sub.id ? "font-medium" : undefined}>{t(sub.label)}</Link>
      </DropdownMenuItem>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}
