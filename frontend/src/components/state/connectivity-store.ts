import { useSyncExternalStore } from "react";
import { createConnectivity, watchConnectivity, type ConnectivitySnapshot } from "../../connectivity.mjs";
import { configuredApiBaseUrl } from "../../api/base";

/** The one flag the whole app shares (design 4.0, 全局不可达): the backend is reachable until a request says otherwise. */
export const connectivity = createConnectivity();

/** The API requests speak for the backend: the base address when the build has one, the same-origin /api/ otherwise. */
const isApiUrl = (url: string) => configuredApiBaseUrl ? url.startsWith(configuredApiBaseUrl) : url.startsWith("/api/");

let watching = false;
/** Start watching the app's own requests (once).  Called from main.tsx before the first request is made. */
export function watchBackend() {
  if (watching || typeof window === "undefined") return;
  watching = true;
  watchConnectivity(connectivity, { host: window, isApi: isApiUrl });
}

export function useBackendDown(): ConnectivitySnapshot {
  return useSyncExternalStore(connectivity.subscribe, connectivity.getSnapshot, connectivity.getSnapshot);
}
