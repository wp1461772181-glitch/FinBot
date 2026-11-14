import { Link } from "react-router";
import { Eye, History, KeyRound, LogOut, Plus } from "lucide-react";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import type { Bot } from "../../api";
import { botSections } from "../../bot-items.mjs";
import { isWaiting, botMarker, countLabel } from "../../bot-marker.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { activeItem, areaItems, areaPath } from "../../shell-nav.mjs";
import { ThemeToggle, useAccountActions } from "./account";
import { openLoginDialog } from "./login-events";
import type { ShellNavProps } from "./AppSidebar";

const sectionTitle = "px-4 pt-3 pb-1 text-caption font-medium text-muted-foreground";
const rowClass = "flex min-h-11 items-center gap-3 rounded-sm px-4 text-body text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-accent aria-[current=page]:font-medium";

/**
 * 「更多」 on the phone (design 3.1): the bots (this is how another bot is reached on a phone until the chat page has its
 * own switcher), the 助手 and 设置 pages, and the account with the light / dark switch.  A bottom drawer (vaul).
 * Loaded on first use, so the tab bar does not carry it.
 */
export default function MoreDrawer({ open, onOpenChange, props }: { open: boolean; onOpenChange: (open: boolean) => void; props: ShellNavProps }) {
  const { t } = useLocale();
  const actions = useAccountActions(props.onModeChange);
  const close = () => onOpenChange(false);
  const { top, groups } = botSections(props.bots);
  const botLinks = [...(top ? [top] : []), ...groups.flatMap(group => group.bots)];
  const assistantItem = activeItem(props.path);
  const mode = props.personal ? t("个人模式") : t("访客只读");
  return <Drawer open={open} onOpenChange={onOpenChange}>
    <DrawerContent aria-describedby="more-drawer-description">
      <DrawerHeader className="pb-0">
        <DrawerTitle>{t("更多")}</DrawerTitle>
        <DrawerDescription id="more-drawer-description" className="sr-only">{t("切换 bot、助手与设置页面、账户")}</DrawerDescription>
      </DrawerHeader>
      <div className="overflow-y-auto pb-[max(1rem,env(safe-area-inset-bottom))]">
        {props.personal && <>
          <p className={sectionTitle}>{t("切换 bot")}</p>
          <ul className="flex flex-col">
            {botLinks.map(bot => {
              const marker = botMarker({ running: props.lineStatus.running.includes(`bot:${bot.id}`), waiting: isWaiting(bot, props.lineStatus.waiting), unread: (bot.unread > 0 ? bot.unread : 0) + (props.lineStatus.unseen.includes(`bot:${bot.id}`) ? 1 : 0), active: bot.id === props.activeBotId });
              return <li key={bot.id}>
                <Link to={bot.is_default ? paths.chat() : paths.chat(bot.id)} onClick={close} aria-current={bot.id === props.activeBotId ? "page" : undefined} className={rowClass}>
                  <span className="min-w-0 flex-1 truncate">{bot.name}</span>
                  {marker.word === "running" && <span className="text-caption text-muted-foreground">{t("回答中")}</span>}
                  {marker.word === "waiting" && <span className="text-caption font-medium text-action">{t("等你")}</span>}
                  {marker.count > 0 && <span className="min-w-5 rounded-full bg-brand px-1.5 text-center text-caption leading-5 font-medium text-primary-foreground">{countLabel(marker.count)}</span>}
                </Link>
              </li>;
            })}
            <li><Link to={paths.chatHistory()} onClick={close} className={rowClass}><History aria-hidden="true" className="size-4 text-muted-foreground" />{t("历史对话")}</Link></li>
            <li><button type="button" onClick={() => { close(); props.onNewBot(); }} className={`${rowClass} w-full text-left`}><Plus aria-hidden="true" className="size-4 text-muted-foreground" />{t("新建 bot")}</button></li>
          </ul>
        </>}
        <p className={sectionTitle}>{t("助手")}</p>
        <ul className="flex flex-col">
          {areaItems("assistant", { personal: props.personal }).map(item => <li key={item.id}><Link to={areaPath("assistant", props.symbol, item.id)} onClick={close} aria-current={props.path.startsWith("/assistant") && assistantItem === item.id ? "page" : undefined} className={rowClass}>{t(item.label)}</Link></li>)}
        </ul>
        <p className={sectionTitle}>{t("设置")}</p>
        <ul className="flex flex-col">
          {areaItems("settings").map(item => <li key={item.id}><Link to={areaPath("settings", props.symbol, item.id)} onClick={close} aria-current={props.path.startsWith("/settings") && assistantItem === item.id ? "page" : undefined} className={rowClass}>{t(item.label)}</Link></li>)}
        </ul>
        <p className={sectionTitle}>{t("账户")}</p>
        <div className="flex items-center gap-2 px-4 py-1"><span className="min-w-0 flex-1 truncate text-body text-muted-foreground">{t("当前")}：{mode}</span><ThemeToggle className="size-11" /></div>
        <ul className="flex flex-col">
          {props.personal
            ? <li><button type="button" onClick={() => { close(); actions.toGuest(); }} className={`${rowClass} w-full text-left`}><Eye aria-hidden="true" className="size-4 text-muted-foreground" />{t("切换到访客只读")}</button></li>
            : <li><button type="button" onClick={() => { close(); openLoginDialog(true); }} className={`${rowClass} w-full text-left`}><KeyRound aria-hidden="true" className="size-4 text-muted-foreground" />{t("登录个人")}</button></li>}
          <li><button type="button" onClick={() => { close(); actions.signOut(); }} className={`${rowClass} w-full text-left`}><LogOut aria-hidden="true" className="size-4 text-muted-foreground" />{t("登出")}</button></li>
        </ul>
      </div>
    </DrawerContent>
  </Drawer>;
}
