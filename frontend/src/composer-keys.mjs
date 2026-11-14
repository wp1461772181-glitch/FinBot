// What a key press means in the chat composer.  Pure, so the Enter / IME rule is tested without a browser.
//
// `composing` is the page's own flag (compositionstart .. compositionend); the event's isComposing and Safari's keyCode 229
// (the Enter that confirms a candidate arrives after compositionend) are read as well.  Any of the three means the key belongs
// to the input method, not to the composer.

export function isImeKey(event, composing = false) {
  return Boolean(composing || event.isComposing || event.keyCode === 229);
}

/**
 * @param event   { key, shiftKey, isComposing, keyCode }
 * @param state   { composing: boolean, menuCount: number }  (menuCount: how many skills the "/" menu lists, 0 = closed)
 * @returns one of "menu-next" | "menu-previous" | "menu-pick" | "menu-close" | "send" | "none"
 */
export function composerKeyAction(event, state) {
  const ime = isImeKey(event, state.composing);
  if (state.menuCount > 0) {
    if (event.key === "ArrowDown" && !ime) return "menu-next";
    if (event.key === "ArrowUp" && !ime) return "menu-previous";
    if ((event.key === "Enter" || event.key === "Tab") && !event.shiftKey && !ime) return "menu-pick";
    if (event.key === "Escape" && !ime) return "menu-close";
  }
  if (event.key !== "Enter" || event.shiftKey || ime) return "none";
  return "send";
}
