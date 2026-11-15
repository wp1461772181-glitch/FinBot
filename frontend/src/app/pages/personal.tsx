import { MemoryPage, NewsSourcesPage } from "../../PersonalPages";
import { useWorkspace } from "../workspace";

/** /assistant/news */
export function NewsRoute() { return <NewsSourcesPage />; }
/** /assistant/memory */
export function MemoryRoute() { return <MemoryPage onNavigate={useWorkspace().go} />; }
