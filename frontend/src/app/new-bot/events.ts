/** The new-bot dialog opens on this window event: the command palette sends it (the sidebar, the phone's lists and the 全部 bot page ask the workspace directly).
 * Only a listener is on the first screen; the dialog itself (app/new-bot/NewBotDialog.tsx) is fetched when it is first asked for. */
export const NEW_BOT_EVENT = "finbot:new-bot";

export function openNewBotDialog() {
  window.dispatchEvent(new Event(NEW_BOT_EVENT));
}
