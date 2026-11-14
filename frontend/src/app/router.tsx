import type { ComponentType } from "react";
import { Navigate, Outlet, createHashRouter, type RouteObject } from "react-router";
import { LegacyFrame } from "../LegacyFrame";
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

/** Every page below is still an old component: the shell puts the old-UI marker around each one (and around nothing else). */
function LegacyPage() { return <LegacyFrame><Outlet /></LegacyFrame>; }

const pages: RouteObject[] = [
  { path: PATTERNS.chat, ...page(() => import("./pages/chat"), "ChatRoute") },
  { path: PATTERNS.chatHistory, ...page(() => import("./pages/chat"), "ChatHistoryRoute") },
  { path: PATTERNS.chatConversation, ...page(() => import("./pages/chat"), "ChatConversationRoute") },
  { path: PATTERNS.chatBotSettings, ...page(() => import("./pages/chat"), "ChatBotRoute", { profile: true }) },
  { path: PATTERNS.chatBot, ...page(() => import("./pages/chat"), "ChatBotRoute") },
  { path: PATTERNS.research, ...page(() => import("./pages/overview"), "ResearchRoute") },
  { path: PATTERNS.companyLatest, ...page(() => import("./pages/latest"), "LatestRoute") },
  { path: PATTERNS.company, ...page(() => import("./pages/overview"), "CompanyRoute") },
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
  { path: PATTERNS.portfolio, ...page(() => import("./pages/portfolio"), "PortfolioRoute") },
  { path: PATTERNS.routines, ...page(() => import("./pages/routines"), "RoutinesRoute") },
  { path: PATTERNS.assistantBots, ...page(() => import("./pages/personal"), "BotsRoute") },
  { path: PATTERNS.assistantSkill, ...page(() => import("./pages/skills"), "SkillsRoute") },
  { path: PATTERNS.assistantSkills, ...page(() => import("./pages/skills"), "SkillsRoute") },
  { path: PATTERNS.assistantMemory, ...page(() => import("./pages/personal"), "MemoryRoute") },
  { path: PATTERNS.assistantNews, ...page(() => import("./pages/personal"), "NewsRoute") },
  { path: PATTERNS.assistantKnowledge, ...page(() => import("./pages/knowledge"), "KnowledgeRoute") },
  ...SETTINGS_SECTIONS.map((section): RouteObject => ({ path: paths.settings(section), ...page(() => import("./pages/settings"), "SettingsRoute") })),
  { path: "*", Component: Fallback },
];

const routes: RouteObject[] = [
  ...(DEV_KIT_ENABLED ? [
    { path: PATTERNS.devKit, ...page(() => import("../dev/KitPage"), "default") },
    { path: PATTERNS.devKitProbe, ...page(() => import("../dev/KitPage"), "default", { probe: true }) },
  ] : []),
  {
    path: "/",
    Component: SessionRoot,
    // Nothing to show while the first page's chunk loads.
    HydrateFallback: () => null,
    children: [
      { index: true, ...to(paths.chat()) },
      { path: PATTERNS.login, ...to(paths.chat()) },
      // The error boundary sits below the layout, so a page that fails to load leaves the shell standing.  It is above the
      // old-UI marker, so the notice it shows is new markup outside it.
      { ErrorBoundary: RouteError, children: [{ Component: LegacyPage, children: pages }] },
    ],
  },
];

normalizeStartupHash();
export const router = createHashRouter(routes);
watchLegacyHashes(router);
