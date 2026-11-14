import { Suspense, lazy, useState } from "react";
import { Navigate, useLocation } from "react-router";
import { AgentChatProviderRoot } from "./chat/ChatSessionProvider";
import { getChatMode } from "../api/base";
import { chatSessionKey } from "../chat-session.mjs";
import { paths } from "../routes.mjs";
import { WorkspaceLayout } from "./WorkspaceLayout";

const LoginPage = lazy(() => import("./LoginPage"));

/** The mode a stored choice restores: null until the reader has picked guest or personal once. */
export function storedChatMode(): "guest" | "personal" | null {
  return localStorage.getItem("market-evidence-agent:chat-mode:v1") ? getChatMode() : null;
}

/**
 * The root of every page except the developer samples.  The reader's mode decides what stands here: the login page
 * while none is chosen (at any address, so a deep link survives the login; the bare address and #/chat move to #/login), and for
 * a read-only guest at #/login, where they can sign in; otherwise the chat session provider with the workspace under it.
 * The provider sits above the routed outlet on purpose: it holds every bot's line (their requests, their drafts, the
 * background answers), so changing page never unmounts it and a bot keeps answering while another page is open.
 */
export function SessionRoot() {
  const [mode, setMode] = useState<"guest" | "personal" | null>(storedChatMode);
  const { pathname } = useLocation();
  // First visit: the bare address (the router has already turned an empty hash into /chat) lands on #/login.
  if (!mode && (pathname === "/" || pathname === paths.chat())) return <Navigate to={paths.login()} replace />;
  if (!mode || (mode === "guest" && pathname === paths.login())) return <Suspense fallback={null}><LoginPage onMode={setMode} /></Suspense>;
  return <AgentChatProviderRoot key={chatSessionKey(mode, localStorage.getItem(mode === "personal" ? "market-evidence-agent:personal-chat-session:v1" : "market-evidence-agent:chat-session:v1"))}><WorkspaceLayout key={mode} onModeChange={setMode} /></AgentChatProviderRoot>;
}
