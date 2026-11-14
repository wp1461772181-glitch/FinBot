import { useState, type CSSProperties, type Dispatch, type SetStateAction } from "react";
import { Link } from "react-router";
import { History, Info, PanelRight, Settings } from "lucide-react";
import { PopPanel } from "@/components/PopPanel";
import { LiveBotOrb } from "../../LiveBotOrb";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { paths } from "../../routes.mjs";
import { type Bot } from "../../api";
import { useLocale } from "../../i18n";
import { useChat } from "./ChatSessionProvider";
import { usePanel } from "./panel-context";

const iconButton = "inline-flex size-9 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-[18px]";

/** What the header's ⓘ says (it replaces the line that used to sit above every conversation, design V5). */
function AboutThisChat() {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  return <span className="relative inline-flex">
    <button type="button" data-testid="about-chat" className={iconButton} aria-haspopup="dialog" aria-expanded={open} aria-label={t("关于这条对话")} title={t("关于这条对话")} onClick={() => setOpen(x => !x)}><Info aria-hidden="true" /></button>
    <PopPanel open={open} onClose={() => setOpen(false)} label={t("关于这条对话")} align="end" className="md:bottom-auto md:top-full md:mb-0 md:mt-2">
      <p className="text-small text-ink-2">{t("消息和研究工具轨迹会保存到服务端；工具按权限读取资料并执行明确请求的系统任务。")}</p>
    </PopPanel>
  </span>;
}

/**
 * The header holds only what belongs to this line: the bot standing there, its name, title and the companies it watches, the way to its
 * settings, and the panel switch.  The mode switch and the global settings live in the sidebar's account menu.
 */
export function ChatHeader({ bot, historyOpen, setHistoryOpen }: { bot?: Bot | null; historyOpen: boolean; setHistoryOpen: Dispatch<SetStateAction<boolean>> }) {
  const { t } = useLocale(), c = useChat(), panel = usePanel();
  const companies = bot?.focus?.companies?.map(company => company.symbol).filter(Boolean) ?? [];
  const subtitle = [bot?.title, companies.join(" · ")].filter(Boolean).join(" · ");
  return (
    <header data-testid="chat-header" className="flex shrink-0 items-center gap-3 px-4 py-2 lg:px-6">
      {bot ? <>
        {/* The avatar keeps its size (BOT_AVATAR_SIZE.title, 44px or more) on every width: the text gives way first. An emoji avatar is a text box, sized here. */}
        <span className="flex shrink-0 [&_.bot-avatar]:h-[var(--avatar)] [&_.bot-avatar]:w-[var(--avatar)]" style={{ "--avatar": `${BOT_AVATAR_SIZE.title}px` } as CSSProperties}><LiveBotOrb key={bot.id} avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.title} chatState={c.state} messages={c.messages} unread={bot.unread > 0 || c.freshExternal} onAcknowledge={c.ackExternal} /></span>
        <div className="min-w-0 flex-1">
          <h1 id="chat-title" className="truncate text-title-s text-ink">{bot.name}</h1>
          {subtitle && <p data-testid="chat-subtitle" className="truncate text-small text-muted-foreground max-sm:hidden">{subtitle}</p>}
        </div>
      </> : <>
        <h1 id="chat-title" className="min-w-0 flex-1 truncate text-title-m text-ink">{t("模型对话")}</h1>
        <button type="button" data-testid="history-toggle" className={`${iconButton} lg:hidden`} aria-expanded={historyOpen} aria-label={t("历史对话")} title={t("历史对话")} onClick={() => setHistoryOpen(x => !x)}><History aria-hidden="true" /></button>
      </>}
      <div className="flex shrink-0 items-center gap-1">
        <AboutThisChat />
        {bot && <Link to={paths.chatSettings(bot.id)} data-testid="bot-settings" className={iconButton} aria-label={t("bot 设置")} title={t("bot 设置")}><Settings aria-hidden="true" /></Link>}
        <button type="button" data-testid="side-toggle" className={`${iconButton} w-auto gap-1.5 px-2.5 text-small aria-expanded:bg-accent aria-expanded:text-ink`} aria-expanded={panel.open} aria-controls="chat-panel" aria-label={panel.open ? t("收起右侧面板") : t("打开右侧面板")} title={panel.open ? t("收起右侧面板") : t("打开右侧面板")} onClick={panel.toggle}><PanelRight aria-hidden="true" /><span className="max-sm:sr-only">{t("面板")}</span></button>
      </div>
    </header>
  );
}
