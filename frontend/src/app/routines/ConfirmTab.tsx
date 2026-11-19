import { lazy, Suspense } from "react";
import { Button } from "@/components/ui/button";
import { BotAvatar } from "@/components/bot/BotAvatar";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { OptionalChunk } from "../../OptionalChunk";
import type { Bot } from "../../api/bots";
import { useLocale } from "../../i18n";
import { entryCard, type ConfirmEntry } from "../../routine-cards.mjs";

const ApprovalCard = lazy(() => import("@/components/ApprovalCard"));

const when = (value: string | null) => (value ? new Date(value).toLocaleString() : "");

/** Who the card is from and where: the bot (with its avatar), what it came from, when. */
function Meta({ entry, bot }: { entry: ConfirmEntry; bot: Bot | undefined }) {
  const { t } = useLocale();
  return <p data-testid="entry-meta" className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-small text-ink-2">
    {bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={20} /> : <span aria-hidden="true" className="size-5 rounded-full bg-sunken" />}
    <span data-testid="entry-bot" className="font-medium text-ink">{bot?.name ?? t("已删除的 bot")}</span>
    <span>·</span>
    <span data-testid="entry-source">{entry.kind === "proposal" ? t("提议的例行任务") : entry.taskName ? `${t("来自任务：")}${entry.taskName}` : t("无人值守的运行")}</span>
    {entry.createdAt && <><span aria-hidden="true">·</span><time dateTime={entry.createdAt} className="font-mono text-muted-foreground">{when(entry.createdAt)}</time></>}
  </p>;
}

/**
 * 待你确认 (design 4.10): the routine cards bots proposed and the writes unattended runs suggested, one list, one confirmation card each (the card of the chat, the action
 * material).  Live ones come first, the newest first; an expired proposal and a write already confirmed stay under them as one folded line.  `onPress(entry, value)`
 * is the page's: what each choice does is the old page's request.  `busy` is the entry being worked on.
 */
export function ConfirmTab({ entries, bots, busy, onPress, loading, error, onRetry }: {
  entries: ConfirmEntry[]; bots: Bot[]; busy: string | null; onPress: (entry: ConfirmEntry, value: string) => Promise<void>;
  loading: boolean; error: unknown; onRetry: () => void;
}) {
  const { t } = useLocale();
  const botOf = (entry: ConfirmEntry) => bots.find(bot => bot.id === entry.botId);
  return <div data-testid="confirm-tab" className="flex min-w-0 flex-col gap-3">
    <p className="max-w-3xl text-small text-muted-foreground">{t("bot 在对话里提出的新建、修改或删除例行任务，要你在对话里的确认卡上点「同意」才生效，确认卡十分钟内有效；定时任务在无人值守时只读不写，它想做的写操作放在这里，不会自动执行。")}</p>
    {error != null && <ErrorBar error={error} onRetry={onRetry} retrying={loading} />}
    {entries.length === 0 && loading && <DelayedSkeleton><div role="status" aria-busy="true" data-testid="confirm-skeleton" className="flex flex-col gap-3"><span className="sr-only">{t("正在读取")}</span>{[0, 1].map(i => <Skeleton key={i} className="h-36 w-full" />)}</div></DelayedSkeleton>}
    {entries.length === 0 && !loading && error == null && <div data-testid="confirm-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("没有等你确认的事")} description={t("bot 提议的例行任务和无人值守时想做的写操作，会出现在这里。")} /></div>}
    {entries.length > 0 && <ul className="m-0 flex list-none flex-col gap-3 p-0">
      {entries.map(entry => {
        const { card, layout } = entryCard(entry);
        const bot = botOf(entry);
        const name = bot?.name ?? t("已删除的 bot");
        const onChoose = (value: string) => onPress(entry, value);
        const none = async () => undefined;
        if (entry.phase !== "live") {
          // Over: one folded line (the card's own: 已过期 · 在对话里再说一次, or 已确认), with the bot in front and, for a proposal, the way to its conversation.
          const label = card.choices.find(choice => choice.value.startsWith("confirm:"))?.label ?? "";
          return <li key={entry.key} data-testid="confirm-entry" data-kind={entry.kind} data-phase={entry.phase} className="flex min-w-0 flex-col gap-1 rounded-md border border-line px-3 py-2.5">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-small">
              {bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={20} /> : <span aria-hidden="true" className="size-5 rounded-full bg-sunken" />}
              <span className="font-medium text-ink-2">{name}</span>
              {entry.phase === "expired" && entry.title && <><span aria-hidden="true" className="text-muted-foreground">·</span><span className="min-w-0 text-ink-2 [overflow-wrap:anywhere]">{entry.title}</span></>}
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <div className="min-w-0 flex-1 basis-56"><OptionalChunk><Suspense fallback={<Skeleton className="h-6 w-48" />}>
                <ApprovalCard card={{ ...card, display: { ...card.display, title: entry.title } } as never} active={entry.phase === "expired"} answered={entry.phase === "done"} reply={entry.phase === "done" ? label : ""}
                  freshAt={entry.phase === "expired" ? 0 : undefined} botName={name} onChoose={none} onChooseMany={none} onReply={none} />
              </Suspense></OptionalChunk></div>
              {entry.phase === "expired" && entry.conversationId && <Button type="button" variant="outline" size="sm" data-testid="entry-open" disabled={busy === entry.id} className="max-sm:h-11" onClick={() => void onChoose("review")}>{t("打开对话")}</Button>}
            </div>
          </li>;
        }
        return <li key={entry.key} data-testid="confirm-entry" data-kind={entry.kind} data-phase="live">
          <OptionalChunk><Suspense fallback={<Skeleton className="h-36 w-full" />}>
            <ApprovalCard card={card as never} arrangement={layout} header={<Meta entry={entry} bot={bot} />} bare={entry.kind === "suggestion"} active={busy !== entry.id} botName={name}
              onChoose={onChoose} onChooseMany={none} onReply={none} />
          </Suspense></OptionalChunk>
        </li>;
      })}
    </ul>}
  </div>;
}
