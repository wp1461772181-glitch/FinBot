import { agentChatUrl } from "../agent-chat-url.mjs";
import { apiErrorMessage } from "../api-errors.mjs";
import { activeChatCredential, applyChatIdentity, changeChatMode, currentChatMode } from "../chat-identity.mjs";

// API base URL is baked in at build time from the VITE_API_BASE_URL repository variable.
export const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

function apiUrl(path: string): string {
  if (!configuredApiBaseUrl) return path;
  const backendPath = path.startsWith("/api/") ? path.slice("/api".length) : path;
  return `${configuredApiBaseUrl}${backendPath}`;
}

async function fetchApi(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = applyChatIdentity(init.headers ?? {}, typeof window === "undefined" ? "" : chatCredential());
  headers.set("Accept", "application/json");
  return fetch(apiUrl(path), { ...init, headers });
}


export type ChatMode = "guest" | "personal";
export function getChatMode(): ChatMode { return currentChatMode(window.localStorage); }
export function setChatMode(mode: ChatMode, credential?: string): void {
  changeChatMode(window.localStorage,window.sessionStorage,mode,credential);
}
function chatCredential(): string {
  return activeChatCredential(window.localStorage,window.sessionStorage,()=>`${crypto.randomUUID()}${crypto.randomUUID()}`);
}

function agentPath(path:string):string { return agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, path); }
function ownerHeaders(json=false):Record<string,string> { return {Accept:"application/json",...(json?{"Content-Type":"application/json"}:{}),"X-Chat-Session":chatCredential()}; }

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `ui-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetchApi(url, init);
  } catch (error) {
    throw error;
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const ownerWrite = ["POST", "PUT", "PATCH", "DELETE"].includes((init.method ?? "GET").toUpperCase());
    if (response.status === 401 && ownerWrite) window.dispatchEvent(new Event("owner-auth-required"));
    throw apiErrorFromPayload(payload, response.status, ownerWrite);
  }
  return payload as T;
}

function apiErrorFromPayload(payload: unknown, status: number, ownerWrite = false): ApiError {
  return new ApiError(apiErrorMessage(payload, status, { ownerWrite }), status);
}


// Shared with the sibling API modules (kept off the declarations so they stay byte-identical to the original).
export { agentPath, apiErrorFromPayload, chatCredential, fetchApi, newIdempotencyKey, ownerHeaders, requestJson };
