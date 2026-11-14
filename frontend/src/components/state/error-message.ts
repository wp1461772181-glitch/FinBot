import { friendlyError } from "../../AgentChatPanel";

/**
 * The reason an ErrorBar gives: the existing `friendlyError` mapping for the backend's error codes and messages, and one plain
 * sentence for a request that never got an answer (the browser's own "Failed to fetch" is not for the reader).
 */
export function errorReason(error: unknown, t: (text: string) => string): string {
  if (error instanceof TypeError) return t("连不上后端，请检查网络后重试。");
  if (error instanceof Error && error.message) return friendlyError(error.message, t);
  if (typeof error === "string" && error) return friendlyError(error, t);
  return t("没有成功，请重试。");
}
