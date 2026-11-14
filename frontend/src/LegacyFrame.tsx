import type { ReactNode } from "react";

/** data-legacy marks the old UI for the restore block in styles/legacy/restore.css; display:contents keeps layout as it was.
 *  Lives outside src/app/ on purpose: Tailwind scans that folder, and the word would become a utility class. */
export function LegacyFrame({ children }: { children: ReactNode }) {
  return <div data-legacy="" style={{ display: "contents" }}>{children}</div>;
}
