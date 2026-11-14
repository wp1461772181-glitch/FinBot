import { Skeleton } from "@/components/state/Skeleton";
import { useLocale } from "../../i18n";
import { useMarkdown } from "./markdown-loader";

/** What stands where the answer's text will be until the renderer chunk is in: the same blocks as the history skeleton. */
export function MessageBodySkeleton() {
  const { t } = useLocale();
  return <div data-slot="skeleton-frame" data-testid="markdown-skeleton" role="status" aria-busy="true" className="flex flex-col gap-2 py-1">
    <span className="sr-only">{t("正在读取")}</span>
    <Skeleton className="h-3.5 w-full" /><Skeleton className="h-3.5 w-11/12" /><Skeleton className="h-3.5 w-3/5" />
  </div>;
}

/**
 * An answer's text.  Renderer not in yet: the skeleton, never the raw Markdown.  Renderer in: the typeset text, with no
 * delay of its own.  Chunk failed: the text as it is (line breaks kept) and a quiet note with 重试; the page around is untouched.
 */
export function MarkdownBody({ plain, text, streaming }: { plain: string; text: string; streaming: boolean }) {
  const { t } = useLocale();
  const { phase, Renderer, retry } = useMarkdown();
  if (Renderer) return <div data-testid="message-body" data-md="ready" data-streaming={streaming || undefined} className="markdown-body chat-prose"><Renderer text={text} /></div>;
  if (phase === "failed") return <>
    <div data-testid="message-body" data-md="plain" className="chat-prose whitespace-pre-wrap break-words">{plain}</div>
    <p data-testid="markdown-failed" className="mt-1 flex items-center gap-2 text-caption text-muted-foreground">
      {t("排版组件没有加载成功，先显示原文。")}
      <button type="button" className="rounded-sm px-1 text-brand underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={retry}>{t("重试")}</button>
    </p>
  </>;
  return <MessageBodySkeleton />;
}
