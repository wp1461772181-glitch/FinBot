import { useContext, type ComponentProps } from "react";
import type { Components } from "react-markdown";
import { citationOrdinal } from "../../chat-citations.mjs";
import { followUpQuestion, parseFlagHref } from "../../chat-unverified.mjs";
import { PUBLIC_MARK_ARIA, normalizePublicMarks, parsePublicMarkHref, publicMarkOrdinal } from "../../chat-public-marks.mjs";
import { useLocale } from "../../i18n";
import { turnKey } from "../../panel-model.mjs";
import { AnswerContext } from "./answer-context";
import { CitationChip } from "./CitationChip";
import { NoteMark, PublicMark, cardButton, cardLine } from "./PublicMark";
import { useChat } from "./ChatSessionProvider";
import { usePanel } from "./panel-context";

// This file belongs to the Markdown renderer's chunk (markdown-renderer.tsx imports it, nothing else does): the hover card and the
// popover behind the chips and marks, and the positioning code they need, load with the renderer and not with the chat page's first screen.

/**
 * What a link in an answer is.  The markdown pipeline turns citation markers, public marks and the old unverified lines into links
 * (chat-citations.mjs, chat-public-marks.mjs, chat-unverified.mjs: the rules are theirs); this decides what each link is drawn as.
 * It is one component for the whole page, reading the answer from context: a component made inside a render would be a new type on
 * every render and the renderer would rebuild each link (and drop its focus) whenever the text grew.
 */
function AnswerLink({ node: _node, ...props }: ComponentProps<"a"> & { node?: unknown }) {
  const { t } = useLocale(), c = useChat(), panel = usePanel(), ctx = useContext(AnswerContext)!;
  const { m, i, draftBox } = ctx, key = turnKey(m, i);
  const href = String(props.href ?? "");

  const publicIndex = parsePublicMarkHref(href);
  if (publicIndex !== null) {
    const view = normalizePublicMarks(m.public_marks)[publicIndex];
    if (!view) return null;
    const ordinal = publicMarkOrdinal(view);
    const cite = ordinal === null ? undefined : m.citations?.find((item, index) => citationOrdinal(item, index) === ordinal);
    return <PublicMark view={view} citation={cite} ordinal={ordinal} onOpenSource={(_citation, from, byKeyboard) => panel.showSource(key, ordinal, from, byKeyboard)} />;
  }

  // The old 「证据不足 / 数字未核实」 lines (messages from before the public marks): the same neutral footnote, the same card, the old words.
  const flag = parseFlagHref(href);
  if (flag) {
    const flagged = m.unverified_lines?.[flag.index];
    return <NoteMark ariaLabel={t(PUBLIC_MARK_ARIA)} testid="line-mark">{(card) => <>
      <span data-slot="line-mark-text" className={`${cardLine} text-ink`}>{props.children}</span>
      {flag.kind === "insufficient" && flagged && <button type="button" data-slot="line-mark-ask" className={cardButton}
        onClick={() => { c.setDraft(followUpQuestion(flagged.line)); card.close(false); draftBox.current?.focus(); }}>{t("追问依据")}</button>}
    </>}</NoteMark>;
  }

  const match = href.match(/^#citation-(\d+)$/);
  const ordinal = match ? Number(match[1]) : null;
  const citation = ordinal ? m.citations?.find((item, index) => citationOrdinal(item, index) === ordinal) : undefined;
  if (match && !citation) return <span className="text-muted-foreground">[{props.children}]</span>;
  if (citation && ordinal) return <CitationChip citation={citation} ordinal={ordinal} turnKey={key}>{props.children}</CitationChip>;
  return <a {...props} target="_blank" rel="noopener noreferrer" />;
}


const TableWrap = ({ node: _node, ...props }: ComponentProps<"table"> & { node?: unknown }) => <div className="markdown-table-wrap"><table {...props} /></div>;
export const ANSWER_COMPONENTS: Components = { table: TableWrap, a: AnswerLink };
