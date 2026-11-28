import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ErrorBar } from "@/components/state/ErrorBar";
import { notify } from "@/components/state/notify";
import { cancelFollowUp, listFollowUps } from "../../../api/follow-ups";
import { useLocale } from "../../../i18n";
import { useLoad } from "../../use-load";

/**
 * 它记着要回头看的事 (活人感 11-28, plan D): what it told him it would look at again, kept so it does.  It writes them in a conversation; here
 * he sees them and can drop one.  Shown only when there is one: nothing to say otherwise.
 */
export function FollowUpsSection() {
  const { t } = useLocale();
  const read = useLoad(signal => listFollowUps(signal));
  const busy = useRef(false);
  const [working, setWorking] = useState<number | null>(null);
  const items = read.data?.items ?? [];
  async function cancel(id: number) {
    if (busy.current) return;
    busy.current = true;
    setWorking(id);
    try {
      await cancelFollowUp(id);
      await read.reload();
      notify.success(t("已取消，它不会再回来看这件事。"), { id: "memory:follow-up" });
    } catch (error) {
      notify.error(error instanceof Error ? error.message : t("取消失败，请重试。"), { id: "memory:follow-up" });
    } finally {
      busy.current = false;
      setWorking(null);
    }
  }
  if (read.error != null && !read.data) return <ErrorBar error={read.error} onRetry={() => void read.reload()} retrying={read.loading} />;
  if (items.length === 0) return null;
  return <section data-testid="memory-follow-ups" aria-labelledby="memory-follow-ups-title" className="flex min-w-0 flex-col gap-2">
    <h2 id="memory-follow-ups-title" className="text-title-s text-ink">{t("它记着要回头看的事")}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{items.length}</span></h2>
    <p className="m-0 max-w-3xl text-small text-muted-foreground">{t("它在对话里答应过回头再看的事。到时间它会去查，有新东西才告诉你；一天最多一条，夜里不打扰。")}</p>
    <ul className="m-0 flex list-none flex-col gap-2 p-0">{items.map(item => <li key={item.id} data-testid="memory-follow-up" data-id={item.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md border border-line bg-surface p-3">
      <span data-testid="memory-follow-up-due" className="font-mono text-caption text-muted-foreground">{item.due_label}</span>
      {item.symbol && <span className="font-mono text-caption text-ink-2">{item.symbol}</span>}
      <p className="m-0 min-w-0 flex-1 basis-60 text-body text-ink [overflow-wrap:anywhere]">{item.what}</p>
      <Button type="button" size="sm" variant="ghost" data-testid="memory-follow-up-cancel" disabled={working === item.id} aria-label={`${t("取消")} · ${item.what}`} className="max-md:h-11" onClick={() => void cancel(item.id)}>{t("取消")}</Button>
    </li>)}</ul>
  </section>;
}
