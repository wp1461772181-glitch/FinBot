import { MemoryPage, MePage, NewsSourcesPage } from "../../PersonalPages";
import { useWorkspace } from "../workspace";

/** /assistant/news */
export function NewsRoute() { return <NewsSourcesPage />; }
/** /assistant/memory */
export function MemoryRoute() { return <MemoryPage onNavigate={useWorkspace().go} />; }
/** /assistant/bots (P5.2 makes it the grid of all bots) */
export function BotsRoute() { return <MePage onNavigate={useWorkspace().go} />; }
