import { useState } from "react";
import { Bookmark } from "lucide-react";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { plainChatPreview } from "../../chat-thread.mjs";
import { readBookmarkedTurns, writeBookmarkedTurns } from "../../question-rail.mjs";
import { useLocale } from "../../i18n";
import type { RailTurn } from "./QuestionRail";

/**
 * The question rail on a phone (design 4.2): 「目录」, a drawer listing this line's questions.  A row jumps to its question; the bookmark keeps it
 * (the same bookmarks the desktop rail keeps, per conversation).
 */
export default function OutlineDrawer({ turns, conversationId, open, onOpenChange }: { turns: RailTurn[]; conversationId: string | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useLocale();
  const [bookmarks, setBookmarks] = useState(() => readBookmarkedTurns(window.localStorage, conversationId));
  const jump = (turn: RailTurn) => {
    onOpenChange(false);
    const message = document.getElementById(`chat-message-${turn.userIndex}`);
    message?.scrollIntoView({ block: "start" });
    if (message) { message.dataset.flash = ""; window.setTimeout(() => message.removeAttribute("data-flash"), 900); }
  };
  const toggle = (turnId: string) => {
    const next = new Set(bookmarks);
    if (next.has(turnId)) next.delete(turnId); else next.add(turnId);
    setBookmarks(next);
    writeBookmarkedTurns(window.localStorage, conversationId, next);
  };
  return <Drawer open={open} onOpenChange={onOpenChange}>
    <DrawerContent data-testid="outline-drawer" aria-describedby="outline-description">
      <DrawerHeader className="pb-0"><DrawerTitle>{t("目录")}</DrawerTitle><DrawerDescription id="outline-description" className="sr-only">{t("这条对话里的问题：点一下跳到它，书签留住它")}</DrawerDescription></DrawerHeader>
      <ol className="flex flex-col overflow-y-auto pb-[max(1rem,env(safe-area-inset-bottom))] pt-2">
        {turns.map((turn, index) => {
          const saved = Boolean(turn.turnId && bookmarks.has(turn.turnId));
          return <li key={turn.userIndex} data-testid="outline-row" className="flex items-stretch">
            <button type="button" data-testid="outline-jump" onClick={() => jump(turn)} className="flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-sm px-4 py-2 text-left text-body text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">
              <span className="w-5 shrink-0 text-right font-mono text-caption text-muted-foreground">{index + 1}</span>
              <span className="min-w-0 flex-1"><span className="block truncate">{plainChatPreview(turn.question, 80)}</span><span className="block truncate text-small text-muted-foreground">{plainChatPreview(turn.answer, 80) || t("尚无回答")}</span></span>
            </button>
            <button type="button" data-testid="outline-bookmark" aria-pressed={saved} disabled={!conversationId || !turn.turnId} aria-label={saved ? t("取消收藏") : turn.turnId ? t("收藏这一轮") : t("这一轮还没保存，暂时不能收藏")} title={saved ? t("取消收藏") : turn.turnId ? t("收藏这一轮") : t("这一轮还没保存，暂时不能收藏")} onClick={() => turn.turnId && toggle(turn.turnId)}
              className="inline-flex size-11 shrink-0 items-center justify-center self-center rounded-sm text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40 aria-pressed:text-brand [&_svg]:size-4"><Bookmark aria-hidden="true" fill={saved ? "currentColor" : "none"} /></button>
          </li>;
        })}
      </ol>
    </DrawerContent>
  </Drawer>;
}
