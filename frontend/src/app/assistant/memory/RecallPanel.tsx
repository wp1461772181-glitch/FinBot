import { useState } from "react";
import { useNavigate } from "react-router";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { listRecall, type RecallItem } from "../../../api/memory";
import { useLocale } from "../../../i18n";
import { recallGroups, recallKindLabel } from "../../../memory-items.mjs";
import { paths } from "../../../routes.mjs";
import { useOpenConversation } from "../../chat/ChatSessionProvider";
import { useWorkspace } from "../../workspace";
import { useLoad } from "../use-load";

const ALL = "__all__"; // Radix Select has no empty item value

/**
 * 往事 (design 4.11): the owner's past conversations, newest first or the best matches for a word, grouped by bot.  A search is sent when it is submitted (the button, or Enter in the box), never while typing;
 * choosing a bot narrows at once.  它们只是线索 — the sentence under the tab says so.  Each one opens its conversation (another bot's line is that bot's page).
 */
export function RecallPanel() {
  const { t } = useLocale();
  const ws = useWorkspace();
  const navigate = useNavigate();
  const openConversation = useOpenConversation();
  const bots = ws.bots.bots;
  const [query, setQuery] = useState(""), [submitted, setSubmitted] = useState(""), [botFilter, setBotFilter] = useState("");
  const data = useLoad(signal => listRecall(submitted, signal, botFilter || null), `${submitted}\n${botFilter}`);
  const items = data.data;
  async function open(item: RecallItem) {
    // Another bot's line is that bot's page; the default bot's and older conversations open as before.
    const bot = bots.find(b => b.id === item.bot_id);
    if (bot && !bot.is_default) { navigate(paths.chat(bot.id)); return; }
    await openConversation(item.conversation_id);
    ws.go("agent");
  }
  const groups = recallGroups(items ?? []) as Array<{ key: string; label: string; items: RecallItem[] }>;
  return <div data-testid="memory-recall" className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-col gap-1.5">
      <p data-testid="memory-note-recall" className="max-w-3xl text-small text-ink-2">{t("说「上次我们聊过……」时，Agent 会在这里找是哪一次对话、聊了什么。往事只是线索，不是证据：回答里的数字仍要重新取证。")}</p>
      <p className="max-w-3xl text-small text-muted-foreground">{t("每个 bot 只回想自己那条线；默认 bot「助理」能回想所有 bot 的。")}</p>
    </div>
    <div role="search" data-testid="recall-search" className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <Input type="search" data-testid="recall-query" value={query} maxLength={200} placeholder={t("搜索往事，例如 英伟达")} aria-label={t("搜索往事")} className="min-w-0 flex-1 max-sm:h-11" onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); setSubmitted(query); } }} />
      <Select value={botFilter || ALL} onValueChange={value => setBotFilter(value === ALL ? "" : value)}>
        <SelectTrigger aria-label={t("按 bot 筛选")} data-testid="recall-bot" className="w-full sm:w-48 max-sm:h-11"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value={ALL}>{t("全部 bot")}</SelectItem>{bots.map(bot => <SelectItem key={bot.id} value={bot.id}>{bot.name}</SelectItem>)}</SelectContent>
      </Select>
      <Button type="button" variant="outline" data-testid="recall-submit" className="max-sm:h-11" onClick={() => setSubmitted(query)}><Search aria-hidden="true" />{t("搜索")}</Button>
    </div>
    {data.error != null && <ErrorBar error={data.error} onRetry={() => void data.reload()} retrying={data.loading} />}
    {!items && data.loading && <DelayedSkeleton><div role="status" aria-busy="true" className="flex flex-col gap-3"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2].map(i => <Skeleton key={i} className="h-20 w-full" />)}</div></DelayedSkeleton>}
    {items && items.length === 0 && <div data-testid="recall-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t(submitted ? "没有找到相关的往事。" : "还没有往事。聊过几次之后，这里会列出最近的对话摘要。")} /></div>}
    {groups.map(group => <section key={group.key} data-testid="recall-group" data-group={group.key} aria-label={group.key === "none" ? t("未归属") : group.label === "已删除的 bot" ? t(group.label) : group.label} className="flex min-w-0 flex-col gap-2">
      <h2 className="text-title-s text-ink">{group.key === "none" ? t("未归属") : group.label === "已删除的 bot" ? t(group.label) : group.label}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{group.items.length}</span></h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">{group.items.map(item => <li key={item.conversation_id} data-testid="recall-item" data-conversation={item.conversation_id} className="flex min-w-0 flex-col gap-1.5 rounded-md border border-line bg-surface p-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <StatusBadge kind="neutral" className="h-5">{t(recallKindLabel(item.kind))}</StatusBadge>
          <strong className="min-w-0 flex-1 basis-48 text-body font-medium text-ink [overflow-wrap:anywhere]">{item.title}</strong>
          {item.date && <span className="font-mono text-caption text-muted-foreground">{item.date}</span>}
        </div>
        <p className="text-small text-ink-2 [overflow-wrap:anywhere]">{item.summary}</p>
        <div><Button type="button" size="sm" variant="outline" data-testid="recall-open" aria-label={`${t("打开对话")} · ${item.title}`} className="max-sm:h-11" onClick={() => void open(item)}>{t("打开对话")}</Button></div>
      </li>)}</ul>
    </section>)}
  </div>;
}
