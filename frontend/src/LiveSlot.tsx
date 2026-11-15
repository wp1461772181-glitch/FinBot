import { Component, Suspense, type ReactNode } from "react";

// The lazy live part of the chat avatar (components/bot/BotPresence.tsx). While its chunk is on the way, and for good if the chunk cannot
// be fetched, the plain still avatar stays: a missing chunk never reaches the page's error screen. It lives in src/ root, not in
// components/: the Tailwind scan turns the word that marks a class's own method into a utility class (see OptionalChunk.tsx).
export class LiveSlot extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : <Suspense fallback={this.props.fallback}>{this.props.children}</Suspense>; }
}
