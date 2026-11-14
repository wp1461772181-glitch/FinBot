// The Markdown pipeline (react-markdown + remark-gfm and their dependencies) and nothing else.  This file is the root of a
// chunk of its own: it is imported only through markdown-loader.ts, so the chat page's first paint does not wait for it.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ANSWER_COMPONENTS } from "./answer-components";

const PLUGINS = [remarkGfm];

/** Renders an answer's text.  The links become citation chips, public marks and line notes (answer-components.tsx; they read their answer from context). */
export function AnswerMarkdown({ text }: { text: string }) {
  return <ReactMarkdown remarkPlugins={PLUGINS} components={ANSWER_COMPONENTS}>{text}</ReactMarkdown>;
}
