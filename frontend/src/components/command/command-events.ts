/** The command palette opens on this window event: the sidebar button, the phone's search entry and the Cmd-K / Ctrl+K shortcut all send it. */
export const COMMAND_MENU_EVENT = "finbot:command-menu";

/** Ask the shell for the palette.  `returnFocus` is where focus goes when it closes (default: what has focus now). */
export function openCommandMenu(returnFocus?: HTMLElement | null) {
  window.dispatchEvent(new CustomEvent(COMMAND_MENU_EVENT, { detail: { returnFocus } }));
}

/** The shortcut: Cmd-K on a Mac, Ctrl+K elsewhere.  Never while an input method is composing. */
export function isPaletteShortcut(event: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "altKey" | "shiftKey" | "isComposing">): boolean {
  return (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && !event.isComposing && event.key.toLowerCase() === "k";
}
