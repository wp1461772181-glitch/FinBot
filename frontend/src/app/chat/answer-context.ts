import { createContext, type RefObject } from "react";
import type { AgentChatMessage } from "../../api/conversations";

/** What the answer's links need to know about the answer they sit in (set by AnswerBody, read by the link components in the renderer chunk). */
export type AnswerCtx = { m: AgentChatMessage; i: number; draftBox: RefObject<HTMLTextAreaElement | null> };
export const AnswerContext = createContext<AnswerCtx | null>(null);
