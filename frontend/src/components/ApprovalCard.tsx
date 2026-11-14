import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Check, Clock, Ellipsis, Hand, Minus, Reply, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import type { AgentChatMessage } from "../api/conversations";
import { answerSummary, approvalKind, arrangeChoices, formatRemaining, isConfirmCard, isExpired, isWriteCard, pickState, remainingMs, targetRows, type ApprovalChoice } from "../approval-card.mjs";
import { clarificationTitle } from "../chat-clarification.mjs";
import { useLocale } from "../i18n";

export type ApprovalCardData = NonNullable<AgentChatMessage["clarification"]>;

type Props = {
  card: ApprovalCardData;
  /** The card can be answered now (it is the newest line, the chat is idle and the reader is signed in). */
  active: boolean;
  /** A later line answered it: the card folds to one line.  `reply` is that line's text ("" when there is none to read). */
  answered?: boolean;
  reply?: string;
  /** When the card arrived in this session (ms); undefined for a card read back from the server, which has no such time. */
  freshAt?: number;
  /** Who is waiting: the screen-reader label. */
  botName?: string;
  onChoose: (value: string) => Promise<void>;
  onChooseMany: (values: string[]) => Promise<void>;
  onReply: (value: string) => Promise<void>;
};

const row = "min-h-11 sm:min-h-9";
const quietButton = "border-line-strong bg-background";

/** `freshAt`'s ten minutes, read against the clock once a second.  null for a card with no time of its own. */
function useCountdown(freshAt: number | undefined, running: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (freshAt === undefined || !running) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [freshAt, running]);
  return freshAt === undefined ? null : { left: remainingMs(freshAt, now), expired: isExpired(freshAt, now) };
}

/** What a card that is over says of itself, in one quiet line. */
function Summary({ card, state, outcome, detail, title }: { card: ApprovalCardData; state: "answered" | "expired"; outcome: string; detail: string; title: string }) {
  const { t } = useLocale();
  const word = state === "expired" ? t("已过期") : outcome === "confirmed" ? t("已确认") : outcome === "cancelled" ? t("已取消") : outcome === "skipped" ? t("未确认") : t("已回答");
  const rest = state === "expired" ? t("在对话里再说一次") : detail;
  const Icon = state === "expired" ? Clock : outcome === "confirmed" ? Check : outcome === "cancelled" ? X : outcome === "skipped" ? Minus : Reply;
  return <div data-slot="approval-card" data-state={state} data-outcome={state === "expired" ? "expired" : outcome} data-kind={approvalKind(card)} role="group" aria-label={title}
    className="flex min-w-0 items-center gap-2 py-1 text-small text-muted-foreground">
    <Icon aria-hidden="true" className="size-4 shrink-0" />
    <span className="min-w-0 truncate"><span className="font-medium text-ink-2">{word}</span>{rest ? ` · ${rest}` : ""}</span>
  </div>;
}

/**
 * The card that waits for the owner's word (design 4.2, 确认卡): the action material, one title, the fields the action will touch, and at most two
 * main buttons (同意 / 取消) with the rest in a 「…」 menu.  Three kinds, one component: a question the bot asks (the choices are the answers, or a
 * line to type), a write waiting for a nod (ten minutes), and a revision's materials, which only the reader may tick.  What each button sends is
 * decided by chat-clarification.mjs through the three callbacks; this component only arranges and enables them.
 * Once answered, or past its ten minutes, it folds to a line.  A card made in this session (`freshAt`) counts its time down; one read back from the
 * server shows only that the time is ten minutes.  Whether a late press is still accepted is the server's answer, not this clock's.
 */
export default function ApprovalCard({ card, active, answered = false, reply = "", freshAt, botName, onChoose, onChooseMany, onReply }: Props) {
  const { t } = useLocale();
  const kind = approvalKind(card), confirm = isConfirmCard(card), write = isWriteCard(card);
  const title = t(clarificationTitle(card));
  const options = card.options ?? [];
  const limits = card.select ?? { min: 1, max: options.length };
  const [picked, setPicked] = useState<string[]>([]);
  const [typed, setTyped] = useState("");
  const [cursor, setCursor] = useState(0);
  const root = useRef<HTMLElement>(null);
  const hintId = useId();
  const countdown = useCountdown(confirm ? freshAt : undefined, active && !answered);

  if (answered) { const summary = answerSummary(card, reply); return <Summary card={card} state="answered" outcome={summary.outcome} detail={summary.detail} title={title} />; }
  if (active && countdown?.expired) return <Summary card={card} state="expired" outcome="expired" detail="" title={title} />;

  const arranged = arrangeChoices(card);
  const need = pickState(card, picked.length);
  // A button that sends the ticked materials waits for the minimum; with nothing to tick, a confirming button has nothing to send.
  const ticks = (choice: ApprovalChoice) => options.length > 0 && /^confirm:/.test(choice.value);
  const blocked = (choice: ApprovalChoice) => !active || (ticks(choice) && need.missing > 0) || (need.noCandidates && /^confirm:/.test(choice.value));
  const press = (choice: ApprovalChoice) => void (ticks(choice) ? onChooseMany(picked) : onChoose(choice.value));
  const reason = !active ? "" : need.noCandidates ? t("没有可用于修订的新材料") : need.missing > 0 ? `${t("至少勾选")} ${need.min} ${t("份材料")}（${t("已选")} ${need.picked}）` : "";

  const move = (event: KeyboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    const group = target.closest<HTMLElement>("[data-approval-group]");
    const keys = group?.dataset.approvalGroup === "list" ? ["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft"] : ["ArrowDown", "ArrowUp"];
    if (group && keys.includes(event.key)) {
      const items = [...group.querySelectorAll<HTMLElement>("[data-approval-option]:not(:disabled)")];
      const at = items.indexOf(target);
      if (at < 0) return;
      event.preventDefault();
      const step = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
      const next = items[(at + step + items.length) % items.length];
      setCursor(Number(next.dataset.approvalOption));
      next.focus();
    } else if (event.key === "Enter" && target instanceof HTMLInputElement && target.type === "checkbox") {
      // Enter on a tick does the card's main thing, as it would from the keyboard anywhere on a form.
      const primary = root.current?.querySelector<HTMLButtonElement>("[data-approval-primary]:not(:disabled)");
      if (primary) { event.preventDefault(); primary.click(); }
    }
  };

  const display = card.display;
  const rows = targetRows(display);
  const label = kind === "question" ? t("等你回答") : t("等你确认");
  return <section ref={root} data-slot="approval-card" data-state={active ? "active" : "locked"} data-kind={kind} data-fresh={countdown ? "" : undefined} role="group" aria-label={botName ? `${botName} · ${title}` : title}
    onKeyDown={move} className="material-action flex min-w-0 flex-col gap-2.5 p-3.5">
    <div className="flex items-center gap-2">
      <span className="material-action-label inline-flex items-center gap-1"><Hand aria-hidden="true" className="size-3.5" />{label}</span>
      {countdown
        ? <span data-slot="approval-timer" data-testid="approval-timer" role="timer" aria-label={t("确认剩余时间")} className="material-action-timer ml-auto">{formatRemaining(countdown.left)}</span>
        : confirm && <span data-slot="approval-note" className="ml-auto text-caption text-muted-foreground">{t("确认有效期为十分钟")}</span>}
    </div>
    <h3 className="text-body font-medium text-ink">{title}</h3>
    {display?.agent_suggestion && <p className="text-small text-ink-2">{t("这是 agent 的建议，不是你的要求。批准后才会继续。")}</p>}
    {card.question && <p className="text-body text-ink">{card.question}</p>}
    {display && <div data-slot="approval-details" className="flex flex-col gap-1.5 border-t border-action/30 pt-2.5 text-small">
      {display.title && <p className="font-medium text-ink">{display.title}</p>}
      {rows.map((target, index) => <dl key={index} className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
        {target.map((field) => <div key={field.key} className="contents"><dt className="text-muted-foreground">{field.known ? t(field.label) : field.label}</dt><dd className="min-w-0 break-words text-ink">{field.value}</dd></div>)}
      </dl>)}
      {display.saved_date && <p className="text-ink-2"><span className="text-muted-foreground">{t("知识库日期")}</span> {display.saved_date}</p>}
      {display.web_date && <p className="text-ink-2"><span className="text-muted-foreground">{t("网页日期")}</span> {display.web_date}</p>}
      {display.url && <p><a href={display.url} target="_blank" rel="noopener noreferrer" className="break-all text-ink underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">{display.url}</a></p>}
      {display.alternative && <p className="text-ink-2">{display.alternative}</p>}
      {confirm && <p className="text-caption text-muted-foreground">{t("改变目标需要重新确认。")}</p>}
    </div>}
    {options.length > 0 && <fieldset disabled={!active} data-approval-group="options" className="flex flex-col gap-0.5 border-t border-action/30 pt-2" aria-describedby={hintId}>
      <legend className="sr-only">{t("用于修订的材料")}</legend>
      {options.map((option, index) => <label key={option.value} className={`flex cursor-pointer items-start gap-2.5 rounded-sm px-1.5 py-2 hover:bg-accent has-[:disabled]:cursor-default has-[:disabled]:hover:bg-transparent ${row}`}>
        <input type="checkbox" data-approval-option={index} tabIndex={index === cursor ? 0 : -1} checked={picked.includes(option.value)} onFocus={() => setCursor(index)}
          onChange={(event) => setPicked((current) => event.target.checked ? (current.length < limits.max ? [...current, option.value] : current) : current.filter((value) => value !== option.value))}
          className="mt-0.5 size-4 shrink-0 accent-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1" />
        <span className="min-w-0"><span className="block text-body text-ink">{option.label}</span>{option.detail && <small className="block text-small text-muted-foreground">{option.detail}</small>}</span>
      </label>)}
    </fieldset>}
    {(reason || need.noCandidates) && <p id={hintId} data-slot="approval-reason" role="status" className="text-small text-ink-2">{reason}</p>}
    {arranged.layout === "confirm"
      ? <div className="flex flex-wrap items-center gap-2">
        {arranged.primary && <Button type="button" data-approval-primary="" disabled={blocked(arranged.primary)} aria-describedby={reason ? hintId : undefined} onClick={() => press(arranged.primary!)} className={`${row} sm:h-9`}>{t(arranged.primary.label)}</Button>}
        {arranged.secondary && <Button type="button" variant="outline" disabled={blocked(arranged.secondary)} onClick={() => press(arranged.secondary!)} className={`${row} sm:h-9 ${quietButton}`}>{t(arranged.secondary.label)}</Button>}
        {arranged.more.length > 0 && <DropdownMenu>
          <DropdownMenuTrigger asChild><Button type="button" variant="ghost" size="icon" disabled={!active} aria-label={t("更多操作")} title={t("更多操作")} className="size-11 sm:size-9"><Ellipsis aria-hidden="true" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="start">{arranged.more.map((choice) => <DropdownMenuItem key={choice.value} disabled={blocked(choice)} onSelect={() => press(choice)}>{t(choice.label)}</DropdownMenuItem>)}</DropdownMenuContent>
        </DropdownMenu>}
      </div>
      : <div data-approval-group="list" role="group" aria-label={title} className="flex flex-wrap items-center gap-2">
        {arranged.list.map((choice, index) => <Button key={choice.value} type="button" variant="outline" data-approval-option={index} tabIndex={index === cursor ? 0 : -1} disabled={blocked(choice)} onFocus={() => setCursor(index)}
          onClick={() => press(choice)} className={`${row} h-auto whitespace-normal py-2 text-left ${quietButton}`}>{t(choice.label)}</Button>)}
      </div>}
    {!write && <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); if (active && typed.trim()) void onReply(typed); }}>
      <label className="flex min-w-0 flex-1 basis-48 flex-col gap-1 text-small text-muted-foreground">{t("手动输入")}
        <input value={typed} onChange={(event) => setTyped(event.target.value)} maxLength={4000} disabled={!active} placeholder={t("也可以输入自己的回答")}
          className={`w-full rounded-sm border border-line-strong bg-background px-3 text-body text-ink outline-none placeholder:text-faint focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 ${row}`} />
      </label>
      <Button type="submit" variant="outline" disabled={!active || !typed.trim()} className={`${row} ${quietButton}`}>{t("发送")}</Button>
    </form>}
  </section>;
}
