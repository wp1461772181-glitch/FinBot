import { Suspense, lazy, type ComponentProps, type ReactNode } from "react";
import { SidebarInset, SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { activeArea, needsLogin } from "../../shell-nav.mjs";
import type { ModeChange } from "./account";
import { AppSidebar, type ShellNavProps } from "./AppSidebar";
import { LoginDialog } from "./LoginDialog";
import { MobileTabBar } from "./MobileTabBar";
import { NeedLogin } from "./NeedLogin";

// The company switcher is only for the research pages: its Combobox (cmdk, popover) loads with them.
const ResearchBar = lazy(() => import("./ResearchBar"));
export type ResearchBarProps = ComponentProps<typeof ResearchBar>;

/** The main column.  The chat fills the screen height (its transcript scrolls inside it); every other page flows and is held to a readable width. */
function Main({ nav, research, children }: { nav: ShellNavProps; research: ResearchBarProps | null; children: ReactNode }) {
  const { isMobile } = useSidebar();
  const chat = activeArea(nav.path) === "chat";
  const guarded = !nav.personal && needsLogin(nav.path);
  // On a phone the tab bar sits over the bottom edge: the column keeps clear of it (and of the home indicator).
  const bar = "3.5rem + env(safe-area-inset-bottom, 0px)";
  return <SidebarInset data-area={chat ? "chat" : undefined} className="min-w-0"
    style={chat ? { height: isMobile ? `calc(100dvh - (${bar}))` : "100dvh", overflow: "hidden" } : isMobile ? { paddingBottom: `calc(${bar})` } : undefined}>
    {research && !guarded && <Suspense fallback={null}><ResearchBar {...research} /></Suspense>}
    {guarded ? <NeedLogin /> : chat
      ? <div className="flex min-h-0 flex-1 flex-col [&>main]:min-h-0 [&>main]:flex-1">{children}</div>
      : <div className="mx-auto w-full max-w-[1280px] flex-1">{children}</div>}
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
export function AppShell({ nav, research, overlay, onModeChange, children }: { nav: ShellNavProps; research: ResearchBarProps | null; overlay?: ReactNode; onModeChange: ModeChange; children: ReactNode }) {
  return <SidebarProvider>
    <AppSidebar props={nav} />
    <Main nav={nav} research={research}>{children}</Main>
    <MobileBar nav={nav} />
    <LoginDialog onModeChange={onModeChange} />
    {overlay}
  </SidebarProvider>;
}
