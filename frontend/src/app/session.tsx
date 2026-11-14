import { useState } from "react";
import { AgentChatProviderRoot } from "../AgentChatPanel";
import { AppEntry, storedChatMode } from "../AppEntry";
import { LegacyFrame } from "../LegacyFrame";
import { chatSessionKey } from "../chat-session.mjs";
import { WorkspaceLayout } from "./WorkspaceLayout";

/**
 * The root of every page except the developer samples.  The reader's mode (guest or personal) decides what stands
 * here: the entry page while none is chosen, else the chat session provider with the workspace under it.  The
 * provider sits above the routed outlet on purpose: it holds every bot's line (their requests, their drafts, the
 * background answers), so changing page never unmounts it and a bot keeps answering while another page is open.
 */
export function SessionRoot() {
  const [mode, setMode] = useState<"guest" | "personal" | null>(storedChatMode);
  return <LegacyFrame>
    {mode
      ? <AgentChatProviderRoot key={chatSessionKey(mode, localStorage.getItem(mode === "personal" ? "market-evidence-agent:personal-chat-session:v1" : "market-evidence-agent:chat-session:v1"))}><WorkspaceLayout key={mode} onModeChange={setMode} /></AgentChatProviderRoot>
      : <AppEntry onMode={setMode} />}
  </LegacyFrame>;
}
