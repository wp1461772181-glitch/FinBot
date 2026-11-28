import { ApiError, agentPath, ownerHeaders } from "./base";

/** One piece of the owner's work (`GET /agent-chat/work`, the list the kernel's list_work reads): a chat turn, a routine, a job started from a card or an
 *  archive build.  `status` is running / queued / done / failed / stopped with the server's own Chinese label; the times come with a `_local` text in his zone. */
export type WorkItem = {
  kind: "chat" | "routine" | "job" | "archive" | string; id: string; title: string; status: string; status_label: string;
  started_at: string | null; started_local: string | null; ended_at: string | null; ended_local: string | null;
  next_run_at: string | null; next_run_local: string | null; failure: string | null; conversation_id: string | null;
};

/** 手上的事: owner only (a guest gets 403). */
export async function getWork(signal?: AbortSignal): Promise<WorkItem[]> {
  const response = await fetch(agentPath("work"), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能查看手上的事。" : "手上的事暂时无法读取。", response.status);
  const data = await response.json().catch(() => null) as { items?: unknown } | null;
  if (!data || !Array.isArray(data.items)) throw new ApiError("手上的事暂时无法读取。", response.status);
  return data.items as WorkItem[];
}
