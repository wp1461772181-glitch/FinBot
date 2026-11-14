import type { AgentChatMessage } from "../../api/conversations";

/** Why a turn failed, as the error bar needs it: the server's code (it decides whether 去设置 is offered), the sentence to show, whether the request never got an answer. */
export type Failure = { code: string; message: string; network: boolean };

/**
 * What only a message made in this tab carries.  `card_at`: when the confirmation card arrived (the 10-minute count starts there; a card read back
 * from the server has no such time).  `failure`: why the turn failed (the server stores a failed turn without the reason).
 * The archive and the server copy leave both out.
 */
export type LiveMessage = AgentChatMessage & { card_at?: number; failure?: Failure };

/** The last request a line sent, so 重试 can send the same one again (a card's answer keeps its request id and label). */
export type SentRequest = { content: string; pendingRequestId?: string; label?: string };
