import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { OWNER_AUTH_EVENT } from "./login-events";
import type { ModeChange } from "./account";

const LoginDialogBody = lazy(() => import("./LoginDialogBody"));

/**
 * The login dialog the whole app shares: a refused write opens it (api.ts raises `owner-auth-required`), and so do the
 * account menu's 登录 and the guest chat's 登录 button.  After a login the reader stays where they were and presses the
 * refused action again, as before (design 4.0, 「需要登录」).  Focus goes back to whatever had it when the dialog
 * opened: Radix returns it to a trigger, and this dialog has none.  Only the listener is in the first load; the dialog
 * (LoginDialogBody) is fetched the first time it is asked for.
 */
export function LoginDialog({ onModeChange }: { onModeChange: ModeChange }) {
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [manual, setManual] = useState(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const show = (event: Event) => {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setManual(Boolean((event as CustomEvent).detail?.manual));
      setLoaded(true); setOpen(true);
    };
    window.addEventListener(OWNER_AUTH_EVENT, show);
    return () => window.removeEventListener(OWNER_AUTH_EVENT, show);
  }, []);
  if (!loaded) return null;
  return <Suspense fallback={null}><LoginDialogBody open={open} onOpenChange={setOpen} manual={manual} returnFocus={returnFocus} onModeChange={onModeChange} /></Suspense>;
}
