import { Suspense, lazy, type ComponentProps, type ReactNode } from "react";
import { useNavigation } from "react-router";
import { SidebarInset, SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { CommandMenuHost } from "@/components/command/CommandMenuHost";
import type { PaletteData } from "@/components/command/CommandMenu";
import { ConfirmHost } from "@/components/state/ConfirmHost";
import { NotifyHost } from "@/components/state/NotifyHost";
import { OfflineBanner } from "@/components/state/OfflineBanner";
import { PageSkeleton, useDelayedFlag } from "@/components/state/Skeleton";
import { TaskDock } from "@/components/state/TaskDock";
import { skeletonKind } from "../../skeleton-kind.mjs";
import { activeArea, needsLogin } from "../../shell-nav.mjs";
import type { ModeChange } from "./account";
import { AppSidebar, type ShellNavProps } from "./AppSidebar";
import { LoginDialog } from "./LoginDialog";
import { MobileTabBar } from "./MobileTabBar";
import { NeedLogin } from "./NeedLogin";

// The company switcher is only for the research pages: its Combobox (cmdk, popover) loads with them.
const ResearchBar = lazy(() => import("./ResearchBar"));
export type ResearchBarProps = ComponentProps<typeof ResearchBar>;

/**
 * While the next page's code loads, the page that is on screen stays; after 400ms a skeleton of the next page's shape covers it
 * (design 4.0), so a quick change never flashes one.  An overlay, not a swap: the page underneath is not unmounted.
 */
function PendingPage() {
  const navigation = useNavigation();
  const target = navigation.state === "loading" ? navigation.location : null;
  const shown = useDelayedFlag(Boolean(target));
  if (!shown || !target) return null;
  return <div data-slot="page-pending" className="absolute inset-0 z-sticky overflow-hidden bg-background"><PageSkeleton kind={skeletonKind(target.pathname + target.search)} /></div>;
}

/** The main column.  The chat fills the screen height (its transcript scrolls inside it); every other page flows and is held to a readable width. */
function Main({ nav, research, children }: { nav: ShellNavProps; research: ResearchBarProps | null; children: ReactNode }) {
  const { isMobile } = useSidebar();
  const chat = activeArea(nav.path) === "chat";
  const guarded = !nav.personal && needsLogin(nav.path);
  // On a phone the tab bar sits over the bottom edge: the column keeps clear of it (and of the home indicator).
  const bar = "3.5rem + env(safe-area-inset-bottom, 0px)";
  return <SidebarInset data-area={chat ? "chat" : undefined} className="min-w-0"
    style={chat ? { height: isMobile ? `calc(100dvh - (${bar}))` : "100dvh", overflow: "hidden" } : isMobile ? { paddingBottom: `calc(${bar})` } : undefined}>
    <OfflineBanner />
    {research && !guarded && <Suspense fallback={null}><ResearchBar {...research} /></Suspense>}
    {guarded ? <NeedLogin /> : chat
      ? <div className="flex min-h-0 flex-1 flex-col [&>main]:min-h-0 [&>main]:flex-1">{children}</div>
      : <div className="mx-auto w-full max-w-[1280px] flex-1">{children}</div>}
    <TaskDock bottom={isMobile ? `calc(${bar})` : "0px"} />
    <PendingPage />
  </SidebarInset>;
}

/** The phone's tab bar exists only below the sidebar's breakpoint, so the page never holds two copies of the navigation (or of the account menu). */
function MobileBar({ nav }: { nav: ShellNavProps }) {
  const { isMobile } = useSidebar();
  return isMobile ? <MobileTabBar props={nav} /> : null;
}

/**
 * The shell around every page (design 3.1 and 4.1): the sidebar on a desktop, the tab bar on a phone, the one global
 * login dialog, and the page in the main column.  No top bar and no footer: each page's own title row is its top.
 * The pages inside are still the old ones; the router wraps each in its own `data-legacy` marker.
 */
export function AppShell({ nav, research, palette, overlay, onModeChange, children }: { nav: ShellNavProps; research: ResearchBarProps | null; palette: PaletteData; overlay?: ReactNode; onModeChange: ModeChange; children: ReactNode }) {
  return <SidebarProvider>
    <AppSidebar props={nav} />
    <Main nav={nav} research={research}>{children}</Main>
    <MobileBar nav={nav} />
    <LoginDialog onModeChange={onModeChange} />
    <ConfirmHost />
    <NotifyHost />
    <CommandMenuHost data={palette} />
    {overlay}
  </SidebarProvider>;
}
