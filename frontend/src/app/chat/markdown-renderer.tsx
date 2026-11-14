// The Markdown pipeline (react-markdown + remark-gfm and their dependencies) and nothing else.  This file is the root of a
// chunk of its own: it is imported only through markdown-loader.ts, so the chat page's first paint does not wait for it.
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const PLUGINS = [remarkGfm];

/** Renders an answer's text.  `components` carries the link rewriting (citations, public marks) and the table wrapper. */
export function AnswerMarkdown({ text, components }: { text: string; components: Components }) {
  return <ReactMarkdown remarkPlugins={PLUGINS} components={components}>{text}</ReactMarkdown>;
}
