import { Component, Suspense, lazy, useEffect, useMemo, useRef, useState, type ComponentType, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { PanelRightClose } from "lucide-react";
import { SkeletonCard } from "@/components/state/Skeleton";
import { ErrorBar } from "@/components/state/ErrorBar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LegacyFrame } from "../../LegacyFrame";
import type { AgentChatMessage } from "../../api/conversations";
import { useLocale } from "../../i18n";
import { PANEL_KEY_STEP, PANEL_MAX, PANEL_MIN, clampPanelWidth, roundQuestion, roundSources, type PanelTab } from "../../panel-model.mjs";
import { useChat } from "./ChatSessionProvider";
import { usePanel } from "./panel-context";
import { usePhone } from "./use-media";
import { OptionalChunk } from "../../OptionalChunk";

// On a phone the panel is a bottom drawer (vaul): the drawer's code is a chunk of its own, fetched the first time the panel opens there.
const PanelDrawer = lazy(() => import("./PanelDrawer"));

/** The panel's tab bodies that need data and code of their own are chunks: the 来源 cards and the 过程 timeline load when their tab opens. */
const loadSources = () => import("./SourcesTab");
const loadProcess = () => import("./ProcessTab");
type PaneProps = { m: AgentChatMessage; i: number; running: boolean };

class PaneBoundary extends Component<{ children: ReactNode; onRetry: () => void; text: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <ErrorBar message={this.props.text} onRetry={this.props.onRetry} /> : this.props.children; }
}

/** A tab body from a chunk.  A chunk that cannot be fetched says so in the tab, with 重试 (a new import), and the rest of the page is untouched. */
function Pane({ load, ...props }: { load: () => Promise<{ default: ComponentType<PaneProps> }> } & PaneProps) {
  const { t } = useLocale();
  const [attempt, setAttempt] = useState(0);
  const Body = useMemo(() => lazy(load), [load, attempt]); // eslint-disable-line react-hooks/exhaustive-deps
  return <PaneBoundary key={attempt} text={t("没有成功，请重试。")} onRetry={() => setAttempt((n) => n + 1)}>
    <Suspense fallback={<SkeletonCard />}><Body {...props} /></Suspense>
  </PaneBoundary>;
}

/** The drag handle on the panel's left edge (from xl up, where the panel is a column): drag, or use the arrow keys; double click puts it back. */
function ResizeHandle({ available }: { available: number }) {
  const { t } = useLocale(), panel = usePanel();
  const start = useRef<{ x: number; width: number } | null>(null);
  const width = clampPanelWidth(panel.width, available);
  const move = (event: ReactPointerEvent) => { if (start.current) panel.setWidth(clampPanelWidth(start.current.width + (start.current.x - event.clientX), available), false); };
  const stop = (event: ReactPointerEvent) => {
    if (!start.current) return;
    panel.setWidth(clampPanelWidth(start.current.width + (start.current.x - event.clientX), available), true);
    start.current = null;
    (event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId);
  };
  const key = (event: ReactKeyboardEvent) => {
    const step = event.shiftKey ? PANEL_KEY_STEP * 4 : PANEL_KEY_STEP;
    const next = event.key === "ArrowLeft" ? width + step : event.key === "ArrowRight" ? width - step : event.key === "Home" ? PANEL_MAX : event.key === "End" ? PANEL_MIN : null;
    if (next === null) return;
    event.preventDefault();
    panel.setWidth(clampPanelWidth(next, available));
  };
  return <div role="separator" aria-orientation="vertical" aria-label={t("调整面板宽度")} aria-valuemin={PANEL_MIN} aria-valuemax={PANEL_MAX} aria-valuenow={width} tabIndex={0}
    data-testid="panel-resize" className="absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize touch-none outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-transparent after:transition-colors hover:after:bg-line-strong focus-visible:after:w-0.5 focus-visible:after:bg-brand xl:block"
    onPointerDown={(event) => { start.current = { x: event.clientX, width }; (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId); event.preventDefault(); }}
    onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} onKeyDown={key} onDoubleClick={() => panel.setWidth(360)} />;
}

/** The workspace cards draw their roomier layout from this panel width on (what the old half-width setting gave them). */
const WIDE_FROM = 520;
const trigger = "h-10 flex-none rounded-none px-3 text-small group-data-[orientation=horizontal]/tabs:after:bottom-0 data-[state=active]:text-ink";

/**
 * The panel's tabs and what is in them: 来源 lists the sources of the round it shows, 过程 the steps of that round, 工作区 is the bot's data cards (and
 * 档案 its profile, until P5.1 gives it a page).  Which round it shows is the one a citation chip or a process bar pointed at, else the newest answer.
 * The same tabs sit in the column beside the thread and in the phone's bottom drawer.
 */
export function PanelTabs({ workspace, profile, wide }: { workspace?: (wide: boolean) => ReactNode; profile?: ReactNode; wide: boolean }) {
  const { t } = useLocale(), c = useChat(), panel = usePanel();
  const m = panel.index >= 0 ? c.messages[panel.index] : null;
  const running = Boolean(m) && panel.index === c.messages.length - 1 && c.state === "sending";
  const sources = m ? roundSources(m).length : 0;
  const when = m?.started_at ? new Date(m.started_at).toLocaleString([], { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const question = m ? roundQuestion(c.messages, panel.index) : "";
  const label = [when, question].filter(Boolean).join(" · ");
  const empty = <p className="px-1 py-6 text-small text-muted-foreground">{t("还没有回答可看。")}</p>;
  const toggle = () => document.querySelector<HTMLElement>("[data-testid=side-toggle]");
  return <Tabs value={panel.tab} onValueChange={(value) => panel.chooseTab(value as PanelTab)} className="min-h-0 flex-1 gap-0">
      <div className="flex shrink-0 items-center border-b border-line pr-1">
        <TabsList variant="line" aria-label={t("右侧面板")} className="h-10 min-w-0 flex-1 justify-start gap-0 overflow-x-auto p-0 px-1 max-lg:h-11">
          <TabsTrigger value="sources" data-testid="tab-sources" className={trigger}>{t("来源")}{sources > 0 && <span className="font-mono text-caption text-muted-foreground">{sources}</span>}</TabsTrigger>
          <TabsTrigger value="process" data-testid="tab-process" className={trigger}>{t("过程")}</TabsTrigger>
          {panel.tabs.includes("workspace") && <TabsTrigger value="workspace" data-testid="tab-workspace" className={trigger}>{t("工作区")}</TabsTrigger>}
          {panel.tabs.includes("profile") && <TabsTrigger value="profile" data-testid="tab-profile" className={trigger}>{t("档案")}</TabsTrigger>}
        </TabsList>
        <button type="button" data-testid="panel-close" aria-label={t("收起右侧面板")} title={t("收起右侧面板")} onClick={() => { panel.setOpen(false); toggle()?.focus(); }}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring max-lg:size-11 [&_svg]:size-4"><PanelRightClose aria-hidden="true" /></button>
      </div>
      {(panel.tab === "sources" || panel.tab === "process") && m && label && <p data-testid="panel-round" className="shrink-0 truncate border-b border-line px-3 py-2 text-caption text-muted-foreground" title={label}>{t("这一轮")}：{label}</p>}
      <TabsContent value="sources" data-testid="sources-pane" className="min-h-0 overflow-y-auto overscroll-contain p-3">{m ? <Pane load={loadSources} m={m} i={panel.index} running={running} /> : empty}</TabsContent>
      <TabsContent value="process" data-testid="process-pane" className="min-h-0 overflow-y-auto overscroll-contain p-3">{m ? <Pane load={loadProcess} m={m} i={panel.index} running={running} /> : empty}</TabsContent>
      {/* The workspace cards and the profile form are still the old markup (their rebuild is not in the chat page's package): each is wrapped on its own, here and nowhere else. */}
      {panel.tabs.includes("workspace") && <TabsContent value="workspace" data-testid="workspace-pane" className="min-h-0 overflow-y-auto overscroll-contain p-3"><LegacyFrame>{workspace?.(wide)}</LegacyFrame></TabsContent>}
      {panel.tabs.includes("profile") && <TabsContent value="profile" data-testid="profile-pane" className="min-h-0 overflow-y-auto overscroll-contain p-3"><LegacyFrame>{profile}</LegacyFrame></TabsContent>}
    </Tabs>;
}

/**
 * The chat page's right panel (design 4.2): the evidence's fixed home.  Above xl it is a column the reader can drag wider and fold away; between lg and
 * xl it lies over the thread; on a phone (below lg) it is a drawer pulled up from the bottom, opened by a citation chip, a process bar or the header's
 * switch, with the same three tabs.
 */
export function ContextPanel({ bot, workspace, profile }: { bot?: { name: string } | null; workspace?: (wide: boolean) => ReactNode; profile?: ReactNode }) {
  const { t } = useLocale(), panel = usePanel(), phone = usePhone();
  const aside = useRef<HTMLElement>(null);
  const [available, setAvailable] = useState(0);
  // The drawer stays mounted once it has been opened, so closing it can slide down instead of vanishing.
  const [drawn, setDrawn] = useState(false);
  useEffect(() => { if (phone && panel.open) setDrawn(true); }, [phone, panel.open]);
  useEffect(() => {
    const host = aside.current?.parentElement;
    if (!host || typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(() => setAvailable(host.clientWidth));
    watch.observe(host); setAvailable(host.clientWidth);
    return () => watch.disconnect();
  }, [panel.open, phone]);
  if (phone) return panel.open || drawn ? <OptionalChunk><Suspense fallback={null}><PanelDrawer bot={bot} workspace={workspace} profile={profile} /></Suspense></OptionalChunk> : null;
  if (!panel.open) return null;

  const width = clampPanelWidth(panel.width, available);
  const toggle = () => document.querySelector<HTMLElement>("[data-testid=side-toggle]");
  const onKeyDown = (event: ReactKeyboardEvent) => {
    // Over the thread (below xl) the panel is a sheet: Esc folds it and gives the focus back to the header's switch.
    if (event.key !== "Escape" || event.defaultPrevented || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
    if (!window.matchMedia?.("(max-width: 1279px)").matches) return;
    panel.setOpen(false); toggle()?.focus();
  };
  return <aside ref={aside} id="chat-panel" data-testid="context-panel" aria-label={bot ? `${bot.name} · ${t("右侧面板")}` : t("右侧面板")} onKeyDown={onKeyDown}
    style={{ "--panel-w": `${width}px` } as React.CSSProperties}
    className="absolute inset-y-0 right-0 z-overlay flex w-[min(380px,100%)] min-w-0 flex-col border-l border-line bg-background shadow-pop max-lg:w-full xl:relative xl:z-auto xl:w-[var(--panel-w)] xl:shrink-0 xl:shadow-none">
    <ResizeHandle available={available} />
    <PanelTabs workspace={workspace} profile={profile} wide={width >= WIDE_FROM} />
  </aside>;
}
