// Which skeleton a page gets while its code loads (design 4.0: "形状与将出现的内容一致").  Pure: an address in, a kind out.
import { splitPath } from "./routes.mjs";

/** "messages" (the chat), "table" (lists the research pages are made of), "cards" (company, scores, monitor), "rows" (everything else). */
export function skeletonKind(path) {
  const { pathname } = splitPath(path);
  const parts = pathname.split("/").filter(Boolean);
  const [head, second] = parts;
  if (head === "chat") return second === "history" ? "rows" : "messages";
  if (head === "research") {
    if (!second) return "cards";
    if (second === "materials" || second === "forecasts" || second === "replay") return "table";
    return "cards";
  }
  if (head === "portfolio") return "table";
  if (head === "routines" || head === "assistant") return "rows";
  if (head === "settings") return "cards";
  return "rows";
}
