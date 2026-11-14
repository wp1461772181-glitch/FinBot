import { CalendarClock } from "lucide-react";
import { parseTaskPostHead } from "../../task-posts.mjs";
import { useLocale } from "../../i18n";

/** The system head of a routine task's result: a line with the task icon above the answer, never the owner's bubble. */
export function TaskPostHead({ content }: { content: string }) {
  const { t } = useLocale();
  const head = parseTaskPostHead(content);
  return <p data-testid="task-post-head" className="flex items-center gap-2 text-small text-muted-foreground">
    <CalendarClock className="size-4 shrink-0" aria-hidden="true" />
    <span className="min-w-0">{head.name ? <>{t("例行任务")}「{head.name}」{head.time ? ` · ${head.time}` : ""}</> : head.raw}</span>
  </p>;
}
