import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { ArrowUp, ChevronUp, Hand, Square } from "lucide-react";
import { useDelayedFlag } from "@/components/state/Skeleton";
import { GuestComposerNotice } from "@/components/GuestComposerNotice";
import { listSkills, getChatMode, type Skill, type Bot } from "../../api";
import { composerKeyAction } from "../../composer-keys.mjs";
import { isActiveClarification } from "../../chat-clarification.mjs";
import { slashMatches } from "../../skill-items.mjs";
import { useLocale } from "../../i18n";
import { ContextMeter } from "./ContextMeter";
import { ModelEffortPicker } from "./ModelEffortPicker";
import { useChat } from "./ChatSessionProvider";
import { focusWaitingCard } from "./approval-focus";

/** The input box grows with what is typed, up to this share of the viewport height, then scrolls inside. */
const MAX_HEIGHT_SHARE = 0.4;

export function Composer({ bot, draftBox, onBotChanged }: { bot?: Bot | null; draftBox: RefObject<HTMLTextAreaElement | null>; onBotChanged?: () => void }) {
  const { t } = useLocale(), c = useChat(), mode = getChatMode();
  const form = useRef<HTMLFormElement>(null);
  // True between compositionstart and compositionend (an input method is building a candidate).  Enter then belongs to it.
  const composing = useRef(false);
  useLayoutEffect(() => {
    const box = draftBox.current; if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, Math.round(window.innerHeight * MAX_HEIGHT_SHARE))}px`;
  }, [c.draft, draftBox]);
  // The "/" menu: a draft like "/财" (no space yet) lists the bot's matching enabled skills, its usual ones first.
  const [skillList, setSkillList] = useState<Skill[] | null>(null), [pickIndex, setPickIndex] = useState(0), [pickClosed, setPickClosed] = useState(false);
  const slashActive = Boolean(bot) && mode === "personal" && c.draft.startsWith("/") && !/\s/.test(c.draft);
  useEffect(() => { if (!slashActive || skillList) return; let live = true; listSkills().then(d => { if (live) setSkillList(d.skills); }).catch(() => { if (live) setSkillList([]); }); return () => { live = false; }; }, [slashActive, skillList]);
  const slashItems = slashActive && !pickClosed ? slashMatches(skillList ?? [], c.draft, bot?.skills ?? []) : [];
  useEffect(() => { setPickIndex(0); setPickClosed(false); }, [c.draft]);
  const current = Math.min(pickIndex, Math.max(0, slashItems.length - 1));
  function pickSkill(skill: Skill) { c.setDraft(`/${skill.name} `); draftBox.current?.focus(); }
  function onKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    const action = composerKeyAction({ key: event.key, shiftKey: event.shiftKey, isComposing: event.nativeEvent.isComposing, keyCode: event.keyCode }, { composing: composing.current, menuCount: slashItems.length });
    if (action === "none") return;
    event.preventDefault();
    if (action === "menu-next" || action === "menu-previous") setPickIndex(i => (i + (action === "menu-next" ? 1 : -1) + slashItems.length) % slashItems.length);
    else if (action === "menu-pick") pickSkill(slashItems[current]);
    else if (action === "menu-close") setPickClosed(true);
    else if (c.draft.trim()) form.current?.requestSubmit();
  }
  const sending = c.state === "sending" || c.state === "testing";
  // A history restore that drags on can be cancelled too; a quick one never flashes the stop button.
  const slowRestore = useDelayedFlag(c.restoring, 1200);
  const stoppable = sending || slowRestore;
  // The bot is waiting on a card in the thread (S9): a strip above the input says so and takes the reader to it.  The input stays usable: a typed line goes out as an ordinary message.
  const waitingCard = !c.archiveView && !c.restoring && c.verified && !sending && isActiveClarification(c.messages, c.messages.length - 1, false);
  const waitingName = bot?.name ?? t("模型");
  const sendDisabled = Boolean(c.archiveView) || c.restoring || !c.verified || !c.draft.trim() || sending;
  const fine = typeof window !== "undefined" && window.matchMedia?.("(pointer: fine) and (min-width: 640px)").matches;
  const placeholder = bot ? `${t("给")} ${bot.name} ${t("发消息…")}${fine ? ` · ${t("Enter 发送，Shift+Enter 换行")}` : ""}` : t(c.verified ? "给 Agent 发消息…" : "登录个人聊天后才能对话");

  if (!c.verified) return <div className="mx-auto w-full max-w-[760px] px-4 pb-4 lg:px-6"><GuestComposerNotice /></div>;
  if (c.archiveView) return <div className="mx-auto w-full max-w-[760px] px-4 pb-4 lg:px-6">
    <div data-slot="archive-composer" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-body text-ink-2">{t("归档是只读的，不能在这里发消息。")}</p>
      <button type="button" data-testid="return-live" onClick={c.returnLive} className="inline-flex h-9 items-center rounded-sm bg-primary px-4 text-body font-medium text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">{t("返回当前对话")}</button>
    </div>
  </div>;
  return <div className="mx-auto w-full max-w-[760px] px-4 pb-[max(1rem,env(safe-area-inset-bottom))] lg:px-6">
    <div role="status" aria-live="polite" className="sr-only">{waitingCard ? `${waitingName} ${t("在等你确认")}` : ""}</div>
    {waitingCard && <button type="button" data-testid="waiting-strip" onClick={() => void focusWaitingCard()} className="material-action mb-2 flex min-h-11 w-full items-center gap-2 px-3 text-left text-small text-ink outline-none hover:brightness-95 focus-visible:ring-2 focus-visible:ring-ring sm:min-h-9">
      <Hand aria-hidden="true" className="size-4 shrink-0 text-action" /><span className="min-w-0 flex-1 truncate">{waitingName} {t("在等你确认上面的卡片")}</span><ChevronUp aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
    </button>}
    {c.status && c.state !== "sending" && c.state !== "error" && <p data-testid="chat-status" role="status" className="mb-2 px-1 text-small text-muted-foreground">{c.status}</p>}
    <form ref={form} data-testid="composer" onSubmit={c.send} className="relative rounded-lg border border-line-strong bg-surface shadow-[0_1px_2px_rgb(0_0_0/0.04)] focus-within:border-ink-2">
      <label htmlFor="agent-draft" className="sr-only">{t("输入消息")}</label>
      {slashItems.length > 0 && <ul id="skill-picker" data-testid="slash-menu" role="listbox" aria-label={t("技能")} className="absolute inset-x-0 bottom-full z-overlay mb-2 max-h-64 overflow-y-auto rounded-md border border-line bg-surface p-1 shadow-pop">
        {slashItems.map((skill, i) => <li key={skill.id} id={`skill-option-${i}`} role="option" aria-selected={i === current} onMouseDown={e => { e.preventDefault(); pickSkill(skill); }}
          className="flex cursor-pointer items-baseline gap-3 rounded-sm px-3 py-2 text-body aria-selected:bg-accent"><strong className="shrink-0 font-mono text-small font-medium text-ink">/{skill.name}</strong><small className="min-w-0 truncate text-small text-muted-foreground">{skill.description}</small></li>)}
      </ul>}
      <textarea id="agent-draft" ref={draftBox} data-testid="draft"
        {...(slashItems.length > 0 ? { role: "combobox", "aria-expanded": true, "aria-controls": "skill-picker", "aria-activedescendant": `skill-option-${current}` } : {})}
        rows={1} value={c.draft} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => c.setDraft(e.target.value)} onKeyDown={onKeyDown}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        maxLength={4000} disabled={c.restoring || sending} placeholder={placeholder}
        className="block max-h-[40dvh] min-h-[44px] w-full resize-none overflow-y-auto bg-transparent px-4 pb-1 pt-3 text-chat text-ink outline-none placeholder:text-faint disabled:opacity-60" />
      <div className="flex items-center justify-between gap-2 px-2 pb-2">
        <div className="flex min-w-0 items-center">
          {bot ? <ModelEffortPicker bot={bot} onBotChanged={onBotChanged ?? (() => undefined)} /> : <span data-testid="model-note" className="truncate px-2 text-caption text-muted-foreground">{c.verified ? `${t("模型")} · ${t("服务器默认模型")}` : t("登录后可用")}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <ContextMeter conversationId={c.conversationId} botId={c.bot?.id ?? null} onCompact={() => void c.compactNow("")} refreshKey={`${c.messages.length}:${c.state === "sending" ? "sending" : "settled"}`} />
          {stoppable
            ? <button type="button" data-testid="stop" aria-label={t("停止")} title={t("停止")} onClick={c.cancel} className={sendButton}><Square className="size-3.5" fill="currentColor" aria-hidden="true" /></button>
            : <button type="submit" data-testid="send" aria-label={t("发送")} title={t("发送")} disabled={sendDisabled} className={sendButton}><ArrowUp className="size-4" aria-hidden="true" /></button>}
        </div>
      </div>
    </form>
  </div>;
}

// The send / stop button: ink on paper.  Its focus ring is the bot's signature colour (design 2.3; one of the three places it shows).
const sendButton = "inline-flex size-9 max-lg:size-11 items-center justify-center rounded-full bg-ink text-background outline-none transition-opacity duration-1 hover:opacity-85 focus-visible:ring-2 focus-visible:ring-bot focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:opacity-30";
