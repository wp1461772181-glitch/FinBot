import { useEffect, type ComponentType } from "react";
import { Navigate, Outlet, createHashRouter, type RouteObject } from "react-router";
import { DelayedSkeleton, PageSkeleton } from "@/components/state/Skeleton";
import { skeletonKind } from "../skeleton-kind.mjs";
import { PATTERNS, SETTINGS_SECTIONS, paths } from "../routes.mjs";
import { RouteError } from "./RouteError";
import { SessionRoot } from "./session";
import { legacyTarget, normalizeStartupHash, watchLegacyHashes } from "./legacy-bridge";

// The route map (design 3.2).  Every page is a lazy route: its chunk is fetched when the address first asks for it,
// so opening the chat does not download the research pages.  The chat session provider sits in SessionRoot, above
// the routed outlet, so a page change never unmounts it.  The addresses come from routes.mjs, the same list the
// links are built from.

// Developer sample page: the flag is a build-time constant, so a build without VITE_DEV_KIT drops the dynamic import and the page's code never reaches dist.
const DEV_KIT_ENABLED = import.meta.env.DEV || import.meta.env.VITE_DEV_KIT === "1";

type Loader = () => Promise<Record<string, unknown>>;
/** A route whose component is the named export of a page module, fetched on first use. */
const page = (load: Loader, name: string, props?: Record<string, unknown>): Pick<RouteObject, "lazy"> => ({
  lazy: async () => {
    const Component = (await load())[name] as ComponentType<Record<string, unknown>>;
    return { Component: props ? () => <Component {...props} /> : Component };
  },
});
const to = (path: string) => ({ element: <Navigate to={path} replace /> });

/** The catch-all: an old-form address the router met before the legacy-address bridge did, or one nobody knows, goes where the old router sent it. */
function Fallback() { return <Navigate to={legacyTarget(window.location.hash)} replace />; }

/** The research area's layout: no markup of its own.  Entering it reads the automatic monitor once (the navigation's dot), through a module that is fetched then. */
function ResearchRoot() {
  useEffect(() => { void import("./research/monitor/read-monitor").then(m => m.entered()).catch(() => 0); }, []);
  return <Outlet />;
}

/** What stands in for the app until the first page's code has arrived (the shell is not mounted yet). */
function FirstLoad() {
  return <DelayedSkeleton><PageSkeleton kind={skeletonKind(window.location.hash.replace(/^#/, "") || "/chat")} /></DelayedSkeleton>;
}

/** The chat pages (P3.2): the line, its history list and the bot's settings page, each its own chunk. */
const chatPages: RouteObject[] = [
  { path: PATTERNS.chat, ...page(() => import("./pages/chat"), "ChatRoute") },
  { path: PATTERNS.chatHistory, ...page(() => import("./pages/chat"), "ChatHistoryRoute") },
  { path: PATTERNS.chatConversation, ...page(() => import("./pages/chat"), "ChatConversationRoute") },
  // The bot's settings are a page of their own (P5.1): the page flows (the shell does not hold it to the chat's screen height) and is its own chunk.
  { path: PATTERNS.chatBotSettings, ...page(() => import("./pages/bot-settings"), "BotSettingsRoute") },
  { path: PATTERNS.chatBot, ...page(() => import("./pages/chat"), "ChatBotRoute") },
];

/**
 * The research area's pages (P6.1–P6.4, P7.3): the watchlist, the company page, the forecast home, one forecast, the earnings judgment, the evidence pages, the material library,
 * 模型成绩, 历史回放 and 监控, plus the `latest` redirect page.  The plain tags among them carry their spacing, link and button values in their own classes.
 */
const researchPages: RouteObject[] = [
  { path: PATTERNS.research, ...page(() => import("./pages/research"), "ResearchRoute") },
  { path: PATTERNS.company, ...page(() => import("./pages/research"), "CompanyRoute") },
  { path: PATTERNS.companyLatest, ...page(() => import("./pages/latest"), "LatestRoute") },
  { path: PATTERNS.forecasts, ...page(() => import("./pages/forecasts"), "ForecastsRoute") },
  { path: PATTERNS.forecast, ...page(() => import("./pages/forecast"), "ForecastRoute") },
  { path: PATTERNS.judgment, ...page(() => import("./pages/judgment"), "JudgmentRoute") },
  { path: PATTERNS.evidenceIndex, ...page(() => import("./pages/evidence"), "EvidenceRoute") },
  { path: PATTERNS.evidenceSource, ...page(() => import("./pages/evidence"), "EvidenceRoute") },
  { path: PATTERNS.evidence, ...page(() => import("./pages/evidence"), "EvidenceRoute") },
  { path: PATTERNS.materials, ...page(() => import("./pages/materials"), "MaterialsRoute") },
  { path: PATTERNS.scores, ...page(() => import("./pages/scores"), "ScoresRoute") },
  { path: PATTERNS.replay, ...page(() => import("./pages/replay"), "ReplayRoute") },
  { path: PATTERNS.monitor, ...page(() => import("./pages/monitor"), "MonitorRoute") },
];

/** 持仓 (P7.1), 任务 (P7.2), 后台 (the owner's read-only backstage), the assistant's skills, memory, news sources, knowledge and 全部 bot pages (P8.1, P9.1) and the five settings pages (P8.2). */
const personalPages: RouteObject[] = [
  { path: PATTERNS.portfolio, ...page(() => import("./pages/portfolio"), "PortfolioRoute") },
  { path: PATTERNS.routines, ...page(() => import("./pages/routines"), "RoutinesRoute") },
  { path: PATTERNS.backstage, ...page(() => import("./pages/backstage"), "BackstageRoute") },
  { path: PATTERNS.backstageTab, ...page(() => import("./pages/backstage"), "BackstageRoute") },
  { path: PATTERNS.assistantSkill, ...page(() => import("./pages/skills"), "SkillsRoute") },
  { path: PATTERNS.assistantSkills, ...page(() => import("./pages/skills"), "SkillsRoute") },
  { path: PATTERNS.assistantMemory, ...page(() => import("./pages/personal"), "MemoryRoute") },
  { path: PATTERNS.assistantNews, ...page(() => import("./pages/personal"), "NewsRoute") },
  { path: PATTERNS.assistantKnowledge, ...page(() => import("./pages/knowledge"), "KnowledgeRoute") },
  { path: PATTERNS.assistantBots, ...page(() => import("./pages/bots"), "BotsRoute") },
  // The five settings addresses are literal routes, so the page is told which one it is (there is no :section parameter to read).
  ...SETTINGS_SECTIONS.map((section): RouteObject => ({ path: paths.settings(section), ...page(() => import("./pages/settings"), "SettingsRoute", { section }) })),
];

const routes: RouteObject[] = [
  ...(DEV_KIT_ENABLED ? [
    { path: PATTERNS.devKit, ...page(() => import("../dev/KitPage"), "default") },
    { path: PATTERNS.devKitProbe, ...page(() => import("../dev/KitPage"), "default", { probe: true }) },
    { path: PATTERNS.devKitStates, ...page(() => import("../dev/StatesPage"), "default") },
    { path: PATTERNS.devKitData, ...page(() => import("../dev/DataPage"), "default") },
    { path: PATTERNS.devKitBots, ...page(() => import("../dev/BotsPage"), "default") },
  ] : []),
  {
    path: "/",
    Component: SessionRoot,
    // While the first page's chunk loads: after 400ms, a skeleton of the shape the address's page will have (a quick load shows nothing).
    HydrateFallback: FirstLoad,
    children: [
      { index: true, ...to(paths.chat()) },
      { path: PATTERNS.login, ...to(paths.chat()) },
      // The error boundary sits below the layout, so a page that fails to load leaves the shell standing.
      { ErrorBoundary: RouteError, children: [...chatPages, ...personalPages, { Component: ResearchRoot, children: researchPages }, { path: "*", Component: Fallback }] },
    ],
  },
];

normalizeStartupHash();
export const router = createHashRouter(routes);
watchLegacyHashes(router);
