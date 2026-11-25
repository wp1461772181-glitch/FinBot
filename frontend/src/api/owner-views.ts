import { ApiError, agentPath, ownerHeaders } from "./base";

export type OwnerViewVersion = { id: string; symbol: string; text: string; quote: string; status: "active" | "superseded" | "dropped" | "archived"; status_label: string; archived_reason?: string | null; created_at: string | null; ended_at: string | null; conversation_id: string | null; turn_id: string | null };

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
/** The owner brings an archived view back (the company page's 恢复).  A refusal (another current view exists) carries the server's own Chinese reason. */
export async function restoreOwnerView(id: string, signal?: AbortSignal): Promise<OwnerViewVersion> {
  const response = await fetch(agentPath(`views/${encodeURIComponent(id)}/restore`), { method: "POST", signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
    const reason = typeof payload?.detail === "string" && /[\u4e00-\u9fff]/.test(payload.detail) ? payload.detail : "";
    throw new ApiError(reason || (response.status === 404 ? "这条已不存在。" : "恢复失败，请重试。"), response.status);
  }
  return (await response.json() as { view: OwnerViewVersion }).view;
}
