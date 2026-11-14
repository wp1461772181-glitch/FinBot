import { useEffect, useSyncExternalStore, type ComponentType } from "react";

// The Markdown renderer is a chunk of its own (markdown-renderer.tsx), fetched in parallel with the first screen: main.tsx
// starts it at launch when the address is the chat, and anything that needs it asks again (the same promise).  Messages show a
// skeleton until it is in and swap to the typeset text in one step; once it is in, rendering is synchronous.  A failed fetch
// leaves the plain text and a retry (see MarkdownBody).

export type MarkdownRenderer = ComponentType<{ text: string }>;
type Phase = "idle" | "loading" | "ready" | "failed";
type Snapshot = { phase: Phase; Renderer: MarkdownRenderer | null };

let snapshot: Snapshot = { phase: "idle", Renderer: null };
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function publish(next: Snapshot) {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

/** Fetch the renderer chunk (once; a call while it is on the way, or after it arrived, joins the same fetch). */
export function loadMarkdown(): Promise<void> {
  if (snapshot.phase === "ready") return Promise.resolve();
  if (inflight) return inflight;
  publish({ phase: "loading", Renderer: null });
  inflight = import("./markdown-renderer").then(
    (module) => { publish({ phase: "ready", Renderer: module.AnswerMarkdown }); },
    () => { inflight = null; publish({ phase: "failed", Renderer: null }); },
  );
  return inflight;
}

/** Start the fetch and forget it (launch time; a failure shows up where the text is). */
export function prefetchMarkdown(): void { void loadMarkdown(); }

const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
const read = () => snapshot;

/** The renderer once it is in, and whether it failed.  A mounted message that finds nothing started asks for it. */
export function useMarkdown() {
  const state = useSyncExternalStore(subscribe, read, read);
  useEffect(() => { if (state.phase === "idle") prefetchMarkdown(); }, [state.phase]);
  return { ...state, retry: prefetchMarkdown };
}
