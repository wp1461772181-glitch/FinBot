import type { ReactNode } from "react";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { useLocale } from "../../i18n";
import { PanelTabs } from "./ContextPanel";
import { usePanel } from "./panel-context";

/**
 * The right panel on a phone (design 4.2): a drawer pulled up from the bottom with the same tabs as the column.  It is open while the panel is
 * (`panel.open`), so a citation chip, a process bar or the header's switch opens it by the same call as on a desktop.  Swiping down, Esc or the
 * panel's own close button fold it.
 */
export default function PanelDrawer({ bot, workspace, profile }: { bot?: { name: string } | null; workspace?: (wide: boolean) => ReactNode; profile?: ReactNode }) {
  const { t } = useLocale(), panel = usePanel();
  const title = bot ? `${bot.name} · ${t("右侧面板")}` : t("右侧面板");
  return <Drawer open={panel.open} onOpenChange={(next) => panel.setOpen(next)}>
    <DrawerContent id="chat-panel" data-testid="context-panel" aria-describedby="chat-panel-description">
      <DrawerHeader className="sr-only"><DrawerTitle>{title}</DrawerTitle><DrawerDescription id="chat-panel-description">{t("来源、过程与工作区")}</DrawerDescription></DrawerHeader>
      <div className="flex h-[min(78dvh,640px)] min-h-0 flex-col pb-[env(safe-area-inset-bottom)]"><PanelTabs workspace={workspace} profile={profile} wide={false} /></div>
    </DrawerContent>
  </Drawer>;
}
