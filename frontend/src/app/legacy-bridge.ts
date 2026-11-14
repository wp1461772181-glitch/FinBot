import type { DataRouter } from "react-router";
import { normalizeHash } from "../legacy-routes.mjs";
import { paths } from "../routes.mjs";
import { storedSymbol } from "./WorkspaceLayout";

// Old-form addresses (#agent, #forecast/<id>, #materials?symbol=…) live on in past answers, routine run records and
// bookmarks.  This is the one place the app listens to hashchange: an address that is not in the new "#/…" form is
// worked out by legacy-routes.mjs and replaced (not pushed), so the back button never bounces between the two forms.

const options = () => ({ lastSymbol: storedSymbol() });

/** Before the router starts: the address the page was opened on, in the new form.  Nothing is pushed. */
export function normalizeStartupHash(): void {
  try {
    const next = normalizeHash(window.location.hash, options());
    if (next !== null) window.history.replaceState(window.history.state, "", `#${next}`);
  } catch { /* the router's catch-all route sends an unreadable address to the chat */ }
}

/** The path an old-form address stands for; the catch-all route uses it too, when the router meets one first. */
export function legacyTarget(hash: string): string {
  return normalizeHash(hash, options()) ?? paths.chat();
}

/** While the app runs: a jump to an old-form address (a link in a past answer, a bookmark) is replaced by the new one. */
export function watchLegacyHashes(router: DataRouter): () => void {
  const onHashChange = () => {
    const next = normalizeHash(window.location.hash, options());
    if (next !== null) void router.navigate(next, { replace: true });
  };
  window.addEventListener("hashchange", onHashChange);
  return () => window.removeEventListener("hashchange", onHashChange);
}
