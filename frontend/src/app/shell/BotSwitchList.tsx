import { Link } from "react-router";
import { History, Plus } from "lucide-react";
import type { Bot } from "../../api/bots";
import { BotAvatar, type AvatarStatus } from "@/components/bot/BotAvatar";
import { isWaiting, botMarker, countLabel } from "../../bot-marker.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";

const rowClass = "flex min-h-11 items-center gap-3 rounded-sm px-4 text-body text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-accent aria-[current=page]:font-medium";

/**
 * The phone's list of bots (design 3.1 / 4.2): each bot with its avatar and the sidebar's marks (answering, waiting for you, unread), then 历史对话
 * and 新建 bot.  The avatar's ring and dot are the same `status` mark the sidebar rows draw (components/bot/BotAvatar).
 * Shared by the 更多 drawer and the chat page's bot switcher, so the two entrances list the same rows in the same way.
 */
export function BotSwitchList({ bots, activeBotId, lineStatus, onNavigate, onNewBot }: {
  bots: Bot[];
  activeBotId: string | null;
  lineStatus: { running: string[]; unseen: string[]; waiting: string[] };
  /** Called when a row is chosen (the drawer closes). */
  onNavigate: () => void;
  onNewBot: () => void;
}) {
  const { t } = useLocale();
  return <ul data-slot="bot-switch-list" className="flex flex-col">
    {bots.map(bot => {
      const marker = botMarker({ running: lineStatus.running.includes(`bot:${bot.id}`), waiting: isWaiting(bot, lineStatus.waiting), unread: (bot.unread > 0 ? bot.unread : 0) + (lineStatus.unseen.includes(`bot:${bot.id}`) ? 1 : 0), active: bot.id === activeBotId });
      const status: AvatarStatus = marker.kind === "running" ? "answering" : marker.kind === "waiting" ? "waiting" : marker.kind === "unread" ? "unread" : "idle";
      return <li key={bot.id}>
        <Link to={bot.is_default ? paths.chat() : paths.chat(bot.id)} onClick={onNavigate} aria-current={bot.id === activeBotId ? "page" : undefined} data-bot-switch-row={bot.id} className={rowClass}>
          <span className="grid shrink-0 place-items-center"><BotAvatar status={status} avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={28} /></span>
          <span className="min-w-0 flex-1 truncate">{bot.name}</span>
          {marker.word === "running" && <span className="text-caption text-muted-foreground">{t("回答中")}</span>}
          {marker.word === "waiting" && <span className="text-caption font-medium text-action">{t("等你")}</span>}
          {marker.count > 0 && <span className="min-w-5 rounded-full bg-brand px-1.5 text-center text-caption leading-5 font-medium text-primary-foreground">{countLabel(marker.count)}</span>}
        </Link>
      </li>;
    })}
    <li><Link to={paths.chatHistory()} onClick={onNavigate} className={rowClass}><History aria-hidden="true" className="size-4 text-muted-foreground" />{t("历史对话")}</Link></li>
    <li><button type="button" onClick={() => { onNavigate(); onNewBot(); }} className={`${rowClass} w-full text-left`}><Plus aria-hidden="true" className="size-4 text-muted-foreground" />{t("新建 bot")}</button></li>
  </ul>;
}
