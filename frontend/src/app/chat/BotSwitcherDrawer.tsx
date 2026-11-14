import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { botSections } from "../../bot-items.mjs";
import { useLocale } from "../../i18n";
import { BotSwitchList } from "../shell/BotSwitchList";
import { useWorkspace } from "../workspace";
import { useChat } from "./ChatSessionProvider";

/** The phone's bot switcher (design 4.2): every bot that is not hidden, with the sidebar's marks, then 历史对话 and 新建 bot.  The 更多 drawer lists the same rows. */
export default function BotSwitcherDrawer({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useLocale(), ws = useWorkspace(), c = useChat();
  const { top, groups } = botSections(ws.bots.bots);
  const bots = [...(top ? [top] : []), ...groups.flatMap((group: { bots: typeof ws.bots.bots }) => group.bots)];
  return <Drawer open={open} onOpenChange={onOpenChange}>
    <DrawerContent data-testid="bot-switcher-drawer" aria-describedby="bot-switcher-description">
      <DrawerHeader className="pb-0"><DrawerTitle>{t("切换 bot")}</DrawerTitle><DrawerDescription id="bot-switcher-description" className="sr-only">{t("选一个 bot，或回到历史对话、新建 bot")}</DrawerDescription></DrawerHeader>
      <div className="overflow-y-auto pb-[max(1rem,env(safe-area-inset-bottom))] pt-2">
        <BotSwitchList bots={bots} activeBotId={c.bot?.id ?? null} lineStatus={c.lineStatus} onNavigate={() => onOpenChange(false)} onNewBot={ws.openNewBot} />
      </div>
    </DrawerContent>
  </Drawer>;
}
