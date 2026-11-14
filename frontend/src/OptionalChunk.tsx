import { Component, Suspense, type ReactNode } from "react";

// Wraps a lazily loaded optional part of a page (the bot's right rail, the new-bot dialog).  While its chunk is on the way
// nothing is drawn; if the chunk cannot be fetched the part stays absent and the page around it keeps working (a failed
// *route* chunk still goes to RouteError).  It lives in src/ root, not src/app/: the Tailwind scan turns the word that
// marks a class's own method into a utility class (see LegacyFrame.tsx, same reason).
export class OptionalChunk extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? null : <Suspense fallback={null}>{this.props.children}</Suspense>; }
}
