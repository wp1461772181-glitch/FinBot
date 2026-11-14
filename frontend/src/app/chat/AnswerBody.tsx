import type { RefObject } from "react";
import type { AgentChatMessage } from "../../api";
import { renderAnswerText } from "../../chat-citations.mjs";
import { evidenceText, hintText, markUnverified, reasonKey } from "../../chat-unverified.mjs";
import { attachPublicMarks } from "../../chat-public-marks.mjs";
import { useLocale } from "../../i18n";
import { AnswerContext } from "./answer-context";
import { MarkdownBody } from "./MarkdownBody";

/** An answer's text: markdown with the citation chips, the public marks and the old unverified-line notes (the renderer, and the components the links become, are a chunk of their own, see MarkdownBody and answer-components.tsx). */
export function AnswerBody({ m, i, streaming, draftBox }: { m: AgentChatMessage; i: number; streaming: boolean; draftBox: RefObject<HTMLTextAreaElement | null> }) {
  const { t } = useLocale();
  const text = renderAnswerText(attachPublicMarks(markUnverified(m.content, m.unverified_lines, { insufficient: t("证据不足"), numbers: t("数字未核实"), reason: (code: string) => t(reasonKey(code)), hint: (item) => hintText(item, t), evidence: (item) => evidenceText(item, t) }), m.public_marks), m.citations, m.citation_protocol);
  return <AnswerContext.Provider value={{ m, i, draftBox }}><MarkdownBody plain={m.content} streaming={streaming} text={text} /></AnswerContext.Provider>;
}
