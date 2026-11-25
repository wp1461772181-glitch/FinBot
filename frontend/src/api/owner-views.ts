import { ApiError, agentPath, ownerHeaders } from "./base";

export type OwnerViewVersion = { id: string; symbol: string; text: string; quote: string; status: "active" | "superseded" | "dropped"; status_label: string; created_at: string | null; ended_at: string | null; conversation_id: string | null; turn_id: string | null };

/** The owner's active view of each company (memory page), newest first.  Owner only: a guest gets 403. */
export async function listOwnerViews(signal?: AbortSignal): Promise<OwnerViewVersion[]> {
  const response = await fetch(agentPath("views"), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能查看你的看法。" : "你的看法暂时无法读取。", response.status);
  const data = await response.json().catch(() => null) as { views?: unknown } | null;
  return Array.isArray(data?.views) ? data.views as OwnerViewVersion[] : [];
}
/** Every version of the owner's view of one company, newest first. */
export async function getOwnerViewHistory(symbol: string, signal?: AbortSignal): Promise<OwnerViewVersion[]> {
  const response = await fetch(agentPath(`views/${encodeURIComponent(symbol)}/history`), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能查看你的看法。" : "你的看法暂时无法读取。", response.status);
  const data = await response.json().catch(() => null) as { versions?: unknown } | null;
  return Array.isArray(data?.versions) ? data.versions as OwnerViewVersion[] : [];
}
/** The owner removes one version from the history (the owner's own click; nothing else deletes a view). */
export async function deleteOwnerView(id: string, signal?: AbortSignal): Promise<void> {
  const response = await fetch(agentPath(`views/${encodeURIComponent(id)}`), { method: "DELETE", signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok && response.status !== 404) throw new ApiError("删除失败，请重试。", response.status);
}
