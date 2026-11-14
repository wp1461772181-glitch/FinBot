import { Suspense, lazy } from "react";
import { useToasterNeeded } from "./toast-store";

const Toaster = lazy(() => import("./toast-impl"));

/** Mounts the toaster once the first toast is wanted; until then the app carries only this stub. */
export function NotifyHost() {
  const needed = useToasterNeeded();
  return needed ? <Suspense fallback={null}><Toaster /></Suspense> : null;
}
