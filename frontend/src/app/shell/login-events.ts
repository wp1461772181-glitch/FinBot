/** The global login dialog opens on this window event (api.ts raises it when a write is refused for want of a login). */
export const OWNER_AUTH_EVENT = "owner-auth-required";

/** Ask the shell for the login dialog.  `manual` says the reader chose to log in (no refused action to retry afterwards). */
export function openLoginDialog(manual = true) {
  window.dispatchEvent(new CustomEvent(OWNER_AUTH_EVENT, { detail: { manual } }));
}
