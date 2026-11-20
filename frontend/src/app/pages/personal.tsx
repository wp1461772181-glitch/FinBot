import { MemoryPage } from "../assistant/memory/MemoryPage";
import { NewsPage } from "../assistant/news/NewsPage";

/** /assistant/news */
export function NewsRoute() { return <NewsPage />; }
/** /assistant/memory, ?tab=recall */
export function MemoryRoute() { return <MemoryPage />; }
