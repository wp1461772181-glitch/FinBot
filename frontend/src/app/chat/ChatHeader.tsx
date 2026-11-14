import { Suspense, lazy, useState, type CSSProperties, type Dispatch, type SetStateAction } from "react";
import { Link } from "react-router";
import { ChevronDown, History, Info, ListTree, PanelRight, Settings } from "lucide-react";
import { PopPanel } from "@/components/PopPanel";
import { OptionalChunk } from "../../OptionalChunk";
import { chatTurnPreviews } from "../../chat-thread.mjs";
import { railShouldShow } from "../../question-rail.mjs";
import { LiveBotOrb } from "../../LiveBotOrb";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { paths } from "../../routes.mjs";
import { type Bot } from "../../api";
import { useLocale } from "../../i18n";
import { useChat } from "./ChatSessionProvider";
import { usePanel } from "./panel-context";
import { usePhone } from "./use-media";

// The phone's two drawers (the bot switcher and 目录) are only needed once pressed: chunks of their own.
const BotSwitcherDrawer = lazy(() => import("./BotSwitcherDrawer"));
const OutlineDrawer = lazy(() => import("./OutlineDrawer"));

const iconButton = "inline-flex size-11 min-w-11 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring lg:size-9 lg:min-w-0 [&_svg]:size-[18px]";

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
  const { t } = useLocale(), c = useChat(), panel = usePanel(), phone = usePhone();
  // The phone's two drawers: the bot switcher (the avatar and name are its button) and 目录 (the question rail, which has no room in a narrow line).
  const [switcher, setSwitcher] = useState(false), [outline, setOutline] = useState(false);
  const [switcherUsed, setSwitcherUsed] = useState(false), [outlineUsed, setOutlineUsed] = useState(false);
  const turns = chatTurnPreviews(c.messages).map(turn => ({ ...turn, turnId: c.messages[turn.userIndex]?.turn_id }));
  const companies = bot?.focus?.companies?.map(company => company.symbol).filter(Boolean) ?? [];
  const subtitle = [bot?.title, companies.join(" · ")].filter(Boolean).join(" · ");
  return (
    <header data-testid="chat-header" className="flex shrink-0 items-center gap-3 px-4 py-2 lg:px-6">
      {bot ? <>
        {/* The avatar keeps its size (BOT_AVATAR_SIZE.title, 44px or more) on every width: the text gives way first. An emoji avatar is a text box, sized here. */}
        {(() => {
          const avatar = <span className="flex shrink-0 [&_.bot-avatar]:h-[var(--avatar)] [&_.bot-avatar]:w-[var(--avatar)]" style={{ "--avatar": `${BOT_AVATAR_SIZE.title}px` } as CSSProperties}><LiveBotOrb key={bot.id} avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.title} chatState={c.state} messages={c.messages} unread={bot.unread > 0 || c.freshExternal} onAcknowledge={c.ackExternal} /></span>;
          // On a phone the avatar and the name are one button: 「在场头像 + bot 名 + ▾」, which opens the bot switcher.
          if (phone && c.verified) return <h1 id="chat-title" className="min-w-0 flex-1 text-title-s text-ink">
            <button type="button" data-testid="bot-switcher" aria-haspopup="dialog" aria-expanded={switcher} title={t("切换 bot")} onClick={() => { setSwitcherUsed(true); setSwitcher(true); }}
              className="flex min-h-11 max-w-full items-center gap-3 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {avatar}<span className="min-w-0 truncate">{bot.name}</span><ChevronDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
            </button>
          </h1>;
          return <>{avatar}<div className="min-w-0 flex-1">
            <h1 id="chat-title" className="truncate text-title-s text-ink">{bot.name}</h1>
            {subtitle && <p data-testid="chat-subtitle" className="truncate text-small text-muted-foreground max-sm:hidden">{subtitle}</p>}
          </div></>;
        })()}
      </> : <>
        <h1 id="chat-title" className="min-w-0 flex-1 truncate text-title-m text-ink">{t("模型对话")}</h1>
        <button type="button" data-testid="history-toggle" className={`${iconButton} lg:hidden`} aria-expanded={historyOpen} aria-label={t("历史对话")} title={t("历史对话")} onClick={() => setHistoryOpen(x => !x)}><History aria-hidden="true" /></button>
      </>}
      <div className="flex shrink-0 items-center gap-1">
        {railShouldShow(turns.length) && <button type="button" data-testid="outline-button" className={`${iconButton} w-auto gap-1.5 px-2.5 text-small max-sm:px-0 lg:hidden`} aria-haspopup="dialog" aria-expanded={outline} onClick={() => { setOutlineUsed(true); setOutline(true); }}><ListTree aria-hidden="true" /><span className="max-sm:sr-only">{t("目录")}</span></button>}
        <AboutThisChat />
        {bot && <Link to={paths.chatSettings(bot.id)} data-testid="bot-settings" className={iconButton} aria-label={t("bot 设置")} title={t("bot 设置")}><Settings aria-hidden="true" /></Link>}
        <button type="button" data-testid="side-toggle" className={`${iconButton} w-auto lg:w-auto gap-1.5 px-2.5 text-small aria-expanded:bg-accent aria-expanded:text-ink`} aria-expanded={panel.open} aria-controls="chat-panel" aria-label={panel.open ? t("收起右侧面板") : t("打开右侧面板")} title={panel.open ? t("收起右侧面板") : t("打开右侧面板")} onClick={panel.toggle}><PanelRight aria-hidden="true" /><span className="max-sm:sr-only">{t("面板")}</span></button>
      </div>
      {phone && switcherUsed && <OptionalChunk><Suspense fallback={null}><BotSwitcherDrawer open={switcher} onOpenChange={setSwitcher} /></Suspense></OptionalChunk>}
      {phone && outlineUsed && <OptionalChunk><Suspense fallback={null}><OutlineDrawer turns={turns} conversationId={c.conversationId} open={outline} onOpenChange={setOutline} /></Suspense></OptionalChunk>}
    </header>
  );
}
