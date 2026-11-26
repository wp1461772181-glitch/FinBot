import { ApiError, agentPath, ownerHeaders } from "./base";
import { watchWriteError } from "../watch-rules-view.mjs";

export type WatchLevel = { threshold: number; level: "remind" | "urgent" | string };
/** One of the owner's own rules (stage 5b-1), as `GET /agent-chat/watch` lists it.  `status` is the server's code or words; `overrides_default` the default it takes the place of (a sentence, or true). */
export type WatchRule = { id: string; symbol: string; metric?: string; direction?: string; levels?: WatchLevel[]; text: string; status: string; last_fired?: string | null; overrides_default?: string | boolean | null };
/** A system default (a preset): `levels` is null when it is not editable; `changed` (when the server says) is whether the owner changed it from the default. */
export type WatchPreset = { key: string; title: string; text: string; enabled: boolean; levels: WatchLevel[] | null; editable: boolean; hard_guarantee: boolean; applies_to?: string[] | string | null; yields_on: string[]; changed?: boolean; overridden?: boolean };
export type AlertSettings = { sensitivity: "quiet" | "standard" | "sensitive" | string; short_moves: boolean; thresholds?: Record<string, unknown> };
export type WatchView = { rules: WatchRule[]; presets: WatchPreset[]; settings: AlertSettings };

/** What the system watches for the owner, in one read: his rules, the system defaults (already with his changes) and the sensitivity.  Owner only. */
export async function getWatch(signal?: AbortSignal): Promise<WatchView> {
  const response = await fetch(agentPath("watch"), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能查看它在盯什么。" : "它在盯什么暂时无法读取。", response.status);
  const data = await response.json().catch(() => null) as Partial<WatchView> | null;
  if (!data || typeof data !== "object") throw new ApiError("它在盯什么暂时无法读取。", response.status);
  return { rules: Array.isArray(data.rules) ? data.rules : [], presets: Array.isArray(data.presets) ? data.presets : [], settings: data.settings ?? { sensitivity: "standard", short_moves: false } };
}

async function write(method: string, path: string, body?: unknown): Promise<unknown> {
  const response = await fetch(agentPath(path), { method, cache: "no-store", headers: ownerHeaders(body !== undefined), ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new ApiError(watchWriteError(response.status, payload?.detail), response.status);
  }
  return await response.json().catch(() => null);
}

/** Turn a system default on or off, or give it new thresholds.  A hard guarantee (the stop price, filings) is refused with a Chinese reason. */
export async function patchWatchPreset(key: string, body: { enabled?: boolean; levels?: WatchLevel[] }): Promise<unknown> {
  return await write("PATCH", `watch-presets/${encodeURIComponent(key)}`, body);
}
/** A system default back to what it was. */
export async function resetWatchPreset(key: string): Promise<unknown> {
  return await write("POST", `watch-presets/${encodeURIComponent(key)}/reset`);
}
/** The sensitivity and/or the 5-minute moves switch. */
export async function putAlertSettings(body: { sensitivity?: string; short_moves?: boolean }): Promise<unknown> {
  return await write("PUT", "alert-settings", body);
}
/** Delete one of his own rules. */
export async function deleteWatchRule(id: string): Promise<void> {
  await write("DELETE", `watch-rules/${encodeURIComponent(id)}`);
}
