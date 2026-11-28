import { ApiError, agentPath, ownerHeaders } from "./base";

/** What it keeps to look at again (``app.follow_ups``): made in a conversation, listed and cancelled on the memory page. */
export type FollowUp = { id: number; what: string; symbol: string | null; status: string; due_at: string; due_label: string; created_at: string | null };

export async function listFollowUps(signal?: AbortSignal): Promise<{ items: FollowUp[]; max_open: number }> {
  const response = await fetch(agentPath("follow-ups"), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能查看。" : "要跟进的事暂时无法读取。", response.status);
  const data = await response.json().catch(() => null) as { items?: unknown; max_open?: unknown } | null;
  return { items: Array.isArray(data?.items) ? data.items as FollowUp[] : [], max_open: typeof data?.max_open === "number" ? data.max_open : 5 };
}

export async function cancelFollowUp(id: number, signal?: AbortSignal): Promise<void> {
  const response = await fetch(agentPath(`follow-ups/${encodeURIComponent(String(id))}`), { method: "DELETE", signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok && response.status !== 404) throw new ApiError("取消失败，请重试。", response.status);
}
