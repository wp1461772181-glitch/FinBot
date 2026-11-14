import { useEffect, useRef, useState, type ReactNode } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PUBLIC_MARK_ARIA, PUBLIC_MARK_GLYPH, publicMarkQuoteText, type PublicMarkView } from "../../chat-public-marks.mjs";
import { useLocale } from "../../i18n";
import type { AgentCitation } from "../../api";

const OPEN_DELAY = 120, CLOSE_DELAY = 180;

/**
 * A neutral footnote on one sentence: a small ◦ that carries no colour of its own and says nothing about the sentence's truth.  The card
 * behind it shows the grounds.  Hover or keyboard focus previews the card; a click, a tap or Enter pins it open and moves the focus into it
 * (so what is in it can be reached with the keyboard); Esc or a click away closes it and a pinned card gives the focus back.
 * (Radix HoverCard takes every control in its card out of the tab order, so it cannot be the card of something that holds a button.)
 */
export function NoteMark({ ariaLabel, testid, children }: { ariaLabel: string; testid: string; children: (card: { trigger: () => HTMLElement | null; close: (restoreFocus?: boolean) => void }) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const pinned = useRef(false), giveBack = useRef(false), timer = useRef(0), button = useRef<HTMLButtonElement>(null);
  const later = (next: boolean, delay: number) => { window.clearTimeout(timer.current); timer.current = window.setTimeout(() => { if (next || !pinned.current) setOpen(next); }, delay); };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const change = (next: boolean) => { window.clearTimeout(timer.current); if (!next) { giveBack.current = pinned.current; pinned.current = false; } setOpen(next); };
  return <Popover open={open} onOpenChange={change}>
    <PopoverTrigger asChild>
      <button type="button" ref={button} data-testid={testid} aria-label={ariaLabel} aria-expanded={open}
        className="mx-0.5 inline-flex size-5 cursor-pointer items-center justify-center rounded-full align-baseline text-body leading-none text-muted-foreground outline-none hover:bg-sunken hover:text-ink-2 focus-visible:ring-2 focus-visible:ring-ring aria-expanded:bg-sunken aria-expanded:text-ink-2"
        onMouseEnter={() => later(true, OPEN_DELAY)} onMouseLeave={() => later(false, CLOSE_DELAY)}
        onFocus={() => later(true, OPEN_DELAY)} onBlur={() => later(false, CLOSE_DELAY)}
        onClick={(event) => {
          event.preventDefault();               // the default toggles; a click here pins instead
          window.clearTimeout(timer.current);
          if (pinned.current) { change(false); return; }
          pinned.current = true; setOpen(true);
        }}>{PUBLIC_MARK_GLYPH}</button>
    </PopoverTrigger>
    <PopoverContent data-testid={`${testid}-card`} role="note" align="start" side="top" className="flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-1.5 p-3 text-small"
      onMouseEnter={() => later(true, 0)} onMouseLeave={() => later(false, CLOSE_DELAY)}
      onOpenAutoFocus={(event) => { if (!pinned.current) event.preventDefault(); }}
      onCloseAutoFocus={(event) => { if (!giveBack.current) event.preventDefault(); giveBack.current = false; }}>
      {children({ trigger: () => button.current, close: (restoreFocus = true) => { if (!restoreFocus) pinned.current = false; change(false); } })}
    </PopoverContent>
  </Popover>;
}

export const cardLine = "text-small [overflow-wrap:anywhere]";
export const cardButton = "inline-flex h-8 w-fit items-center rounded-sm px-2 -ml-2 text-small font-medium text-brand outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring";

/**
 * The public mark (U9) on a sentence.  The card shows what the server sent, word for word: its template, the verbatim source quote and
 * 「查看来源 [n]», which points the right panel at the same card the citation chip points at.
 */
export function PublicMark({ view, citation, ordinal, onOpenSource }: { view: PublicMarkView; citation: AgentCitation | undefined; ordinal: number | null; onOpenSource: (citation: AgentCitation, from: HTMLElement | null, byKeyboard: boolean) => void }) {
  const { t } = useLocale();
  return <NoteMark ariaLabel={t(PUBLIC_MARK_ARIA)} testid="public-mark">{(card) => <>
    <span data-slot="public-mark-template" className={`${cardLine} text-ink`}>{view.label}</span>
    <span data-slot="public-mark-quote" className={`${cardLine} font-quote text-ink-2`}>{publicMarkQuoteText(view, t)}</span>
    {citation && ordinal !== null && <button type="button" data-slot="public-mark-cite" className={cardButton}
      onClick={(event) => { const byKeyboard = event.detail === 0; const from = card.trigger(); card.close(false); onOpenSource(citation, from, byKeyboard); }}>{t("查看来源")} [{ordinal}]</button>}
  </>}</NoteMark>;
}
