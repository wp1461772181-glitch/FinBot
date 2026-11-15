import { useCallback, useEffect, useMemo, useState, type MutableRefObject } from "react";
import { useNavigate } from "react-router";
import { Bot as BotIcon, Building2, EyeOff, FileText, MessageSquare, Plus } from "lucide-react";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { listAgentConversations, type ConversationSummary } from "../../api/conversations";
import { type Bot } from "../../api/bots";
import { arrange, botItems, companyItems, pageItems, recentItems, type PaletteRow } from "../../command-items.mjs";
import { useLocale } from "../../i18n";
import { DelayedSkeleton, SkeletonRows } from "../state/Skeleton";
import { ErrorBar } from "../state/ErrorBar";

/** What the palette lists and what choosing a company does: held by the shell, which already has the watch list and the bots. */
export type PaletteData = {
  personal: boolean;
  /** The company the reader is on: the library and evidence pages take it in their address. */
  symbol: string;
  symbols: string[];
  bots: Bot[];
  /** A company on the watch list was chosen: the shell's own "switch to this company" (the research bar's). */
  onSelectCompany: (ticker: string) => void;
  /** A valid ticker that is not on the watch list: add it (the shell's existing add) and open it. */
  onAddCompany: (ticker: string) => void;
};

type Recents = { status: "idle" | "loading" | "ready" | "error"; items: ConversationSummary[]; error: unknown };

/** The latest conversations: fetched when the palette opens (not before), with the existing history call, newest first. */
function useRecents(open: boolean, enabled: boolean) {
  const [state, setState] = useState<Recents>({ status: "idle", items: [], error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open || !enabled) return;
    const controller = new AbortController();
    setState((previous) => ({ ...previous, status: "loading", error: null }));
    listAgentConversations(0, controller.signal)
      .then(({ conversations }) => {
        if (controller.signal.aborted) return;
        const newest = [...conversations].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
        setState({ status: "ready", items: newest, error: null });
      })
      .catch((error) => { if (!controller.signal.aborted) setState((previous) => ({ ...previous, status: "error", error })); });
    return () => controller.abort();
  }, [open, enabled, attempt]);
  return { ...state, retry: () => setAttempt((n) => n + 1) };
}

const ICON = { company: Building2, add: Plus, bot: BotIcon, page: FileText, recent: MessageSquare } as const;

/**
 * 命令面板 (Cmd-K, design 4.1): jump to a company, a bot, a page or a recent conversation.  Dialog + cmdk, filtering done by
 * command-items.mjs (the rows come ranked, so the first one on screen is the best match and Enter opens what was typed).
 * Typing a valid code that is not on the watch list offers 加入自选并打开.  Every jump is a router navigation to an address from
 * routes.mjs.  Focus goes back to where the reader was.
 */
export default function CommandMenu({ open, onOpenChange, returnFocus, data }: { open: boolean; onOpenChange: (open: boolean) => void; returnFocus: MutableRefObject<HTMLElement | null>; data: PaletteData }) {
  const { t, locale } = useLocale();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  useEffect(() => { if (!open) setQuery(""); }, [open]);
  const recent = useRecents(open, data.personal);

  const sources = useMemo(() => ({
    companies: companyItems(data.symbols, { locale }),
    bots: data.personal ? botItems(data.bots, { t }) : [],
    pages: pageItems({ personal: data.personal, symbol: data.symbol, t }),
    recents: data.personal ? recentItems(recent.items, { t }) : [],
    symbols: data.symbols,
  }), [data.symbols, data.bots, data.personal, data.symbol, recent.items, locale, t]);
  const groups = useMemo(() => arrange(query, sources), [query, sources]);

  const choose = useCallback((row: PaletteRow) => {
    onOpenChange(false);
    if (row.kind === "company" && row.symbol) data.onSelectCompany(row.symbol);
    else if (row.kind === "add" && row.symbol) data.onAddCompany(row.symbol);
    else navigate(row.path);
  }, [data, navigate, onOpenChange]);

  const heading: Record<string, string> = { company: t("公司"), bot: "bot", page: t("页面"), recent: t("最近对话") };
  const recentLoading = data.personal && (recent.status === "loading" || recent.status === "idle");
  const recentFailed = data.personal && recent.status === "error";
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent showCloseButton={false} closeLabel={t("关闭")} className="top-[20%] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-xl" data-slot="command-menu"
      onCloseAutoFocus={(event) => { event.preventDefault(); const target = returnFocus.current ?? document.querySelector<HTMLElement>("[data-more-trigger]"); window.setTimeout(() => { const back = target?.isConnected ? target : document.querySelector<HTMLElement>("[data-more-trigger]"); back?.focus(); }, 0); }}>
      <DialogHeader className="sr-only">
        <DialogTitle>{t("命令面板")}</DialogTitle>
        <DialogDescription>{t("跳到公司、bot、页面或最近的对话。输入代码可直接打开一家公司。")}</DialogDescription>
      </DialogHeader>
      <Command shouldFilter={false} loop label={t("命令面板")} className="rounded-lg">
        <CommandInput value={query} onValueChange={setQuery} placeholder={t("搜索公司、bot、页面或对话；输入代码直接打开")} autoCapitalize="off" autoCorrect="off" spellCheck={false} aria-label={t("命令面板")} />
        <CommandList className="max-h-[min(24rem,60dvh)]">
          {!groups.length && !recentLoading && !recentFailed && <CommandEmpty>{t("没有匹配的结果")}</CommandEmpty>}
          {groups.map((group) => <CommandGroup key={group.id} heading={heading[group.id]}>
            {group.rows.map((row) => {
              const Icon = row.kind === "bot" && row.hidden ? EyeOff : ICON[row.kind];
              return <CommandItem key={row.id} value={row.id} onSelect={() => choose(row)} data-kind={row.kind}>
                <Icon aria-hidden="true" />
                {row.kind === "add"
                  ? <span className="min-w-0 flex-1 truncate">{t("加入自选并打开")} <span className="font-mono">{row.label}</span></span>
                  : <>
                    <span className={`min-w-0 truncate ${row.kind === "company" ? "font-mono" : ""}`}>{row.label}</span>
                    {row.kind === "company" && row.note && <span className="min-w-0 truncate text-caption text-muted-foreground">{row.note}</span>}
                    {row.kind === "bot" && row.note && <span className="ml-auto shrink-0 text-caption text-muted-foreground">{row.note}</span>}
                    {row.kind === "page" && row.area && <span className="ml-auto shrink-0 text-caption text-muted-foreground">{row.area}</span>}
                  </>}
              </CommandItem>;
            })}
            {group.id === "recent" && recentLoading && null}
          </CommandGroup>)}
          {recentLoading && !groups.some((group) => group.id === "recent") && <div className="px-3 py-2" data-slot="command-recent-loading">
            <p className="px-0 py-1.5 text-xs font-medium text-muted-foreground">{t("最近对话")}</p>
            <DelayedSkeleton><SkeletonRows rows={3} /></DelayedSkeleton>
          </div>}
          {recentFailed && <div className="p-2" data-slot="command-recent-error"><ErrorBar error={recent.error} onRetry={recent.retry} /></div>}
        </CommandList>
      </Command>
    </DialogContent>
  </Dialog>;
}
