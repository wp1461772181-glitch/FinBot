import { ApiError, agentPath, ownerHeaders } from "./base";

/** How much the assistant may do without a confirmation card (``app.permission_mode``): ask = 每步都问, default = 默认, full = 完全放行. */
export type PermissionMode = "ask" | "default" | "full";
export type PermissionView = { mode: PermissionMode; label: string; modes: { mode: PermissionMode; label: string }[] };

export async function getPermissionMode(signal?: AbortSignal): Promise<PermissionView> {
  const response = await fetch(agentPath("permission-mode"), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能设置权限。" : "权限设置暂时无法读取。", response.status);
  return await response.json() as PermissionView;
}

export async function putPermissionMode(mode: PermissionMode): Promise<PermissionView> {
  const response = await fetch(agentPath("permission-mode"), { method: "PUT", cache: "no-store", headers: ownerHeaders(true), body: JSON.stringify({ mode }) });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能设置权限。" : "保存失败，请重试。", response.status);
  return await response.json() as PermissionView;
}
