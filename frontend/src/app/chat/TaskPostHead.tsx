// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { parseTaskPostHead } from "../../task-posts.mjs";
import { useLocale } from "../../i18n";

export /** The system head of a routine task's result: a small label above the answer, never the owner's bubble. */
function TaskPostHead({ content }: { content: string }) {
  const { t } = useLocale();
  const head = parseTaskPostHead(content);
  return <p className="task-post-head">{head.name ? <>{t("例行任务")}「{head.name}」{head.time ? ` · ${head.time}` : ""}</> : head.raw}</p>;
}
