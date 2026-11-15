import type { PriceHistory, V2Workspace } from "../types";
import { requestJson } from "./base";

export async function getV2Workspace(symbol: string, signal?: AbortSignal): Promise<V2Workspace> {
  return requestJson<V2Workspace>(`/api/v2/stocks/${encodeURIComponent(symbol)}/workspace`, { signal });
}

export async function getV2Prices(symbol: string, signal?: AbortSignal): Promise<{ symbol: string; price_history: PriceHistory }> {
  return requestJson<{ symbol: string; price_history: PriceHistory }>(`/api/v2/stocks/${encodeURIComponent(symbol)}/prices`, { signal });
}

