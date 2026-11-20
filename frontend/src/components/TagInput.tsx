// A tag input (design 5.4): typed or pasted items become tags; an item that does not pass `validate` is not entered, stays in the box in the danger colour
// and the field says which.  Built here and not taken from `emblor` (the design's suggestion; MIT, 238 kB unpacked, and it brings cmdk 0.2, an old
// radix dialog and a sort library next to the ones the app already has); the part this app needs is a hundred lines.
//   Enter / comma / semicolon / space: enter what is typed.  Paste of several items: enter them all.  Leaving the box: enter what is typed.
//   Backspace in an empty box: take the last tag back.  Each tag has its own remove button.  Valid items of one entry go in even when another is refused.
import { useId, useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale, colon } from "../i18n";
import { SPLIT, readTags } from "../tag-input.mjs";

export function TagInput({ id, value, onChange, normalize = (raw) => raw.trim(), validate = () => true, max, invalidLabel, limitLabel, placeholder, disabled, label, describedBy, className, testid }: {
  id?: string; value: readonly string[]; onChange: (next: string[]) => void;
  normalize?: (raw: string) => string; validate?: (item: string) => boolean; max?: number;
  /** "不是股票代码": said with the refused items after it. */
  invalidLabel: string; limitLabel?: string;
  placeholder?: string; disabled?: boolean; label?: string; describedBy?: string; className?: string; testid?: string;
}) {
  const { t } = useLocale();
  const own = useId(), inputId = id ?? own, messageId = `${inputId}-message`;
  const [text, setText] = useState(""), [message, setMessage] = useState("");
  const box = useRef<HTMLInputElement>(null);
  const invalid = Boolean(message) && message !== limitLabel;

  function enter(source: string) {
    const { add, invalid: refused, cut } = readTags(source, value, { normalize, validate, max });
    if (add.length) onChange([...value, ...add]);
    setText(refused.join(" "));
    setMessage(refused.length ? `${invalidLabel}${colon()}${refused.join(", ")}` : cut && limitLabel ? limitLabel : "");
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return; // an input method is choosing its candidates
    if (event.key === "Enter" || event.key === "," || event.key === ";" || event.key === "，" || (event.key === " " && text.trim())) {
      event.preventDefault();
      if (text.trim()) enter(text);
    } else if (event.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1)); setMessage("");
    }
  };
  const onPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData("text");
    if (!SPLIT.test(pasted.trim())) return; // one item: it lands in the box as usual
    event.preventDefault();
    enter(`${text} ${pasted}`);
  };
  return <div data-slot="tag-input" data-testid={testid} className={cn("grid gap-1.5", className)}>
    <div aria-invalid={invalid || undefined} onClick={() => box.current?.focus()}
      className={cn("flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-sm border border-input bg-transparent px-2 py-1 shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 dark:bg-input/30 max-md:min-h-11",
        "aria-invalid:border-danger aria-invalid:focus-within:ring-danger/25", disabled && "pointer-events-none opacity-50")}>
      <ul aria-label={label} className="contents">
        {value.map((item) => <li key={item} data-tag={item} className="inline-flex items-center gap-1 rounded-sm border border-line bg-sunken py-0.5 pr-0.5 pl-2 font-mono text-small text-ink">
          <span>{item}</span>
          <button type="button" aria-label={`${t("移除")} ${item}`} disabled={disabled} onClick={(event) => { event.stopPropagation(); onChange(value.filter((x) => x !== item)); setMessage(""); box.current?.focus(); }}
            className="inline-flex size-5 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring max-md:size-7"><X aria-hidden="true" className="size-3.5" /></button>
        </li>)}
      </ul>
      <input ref={box} id={inputId} value={text} disabled={disabled} placeholder={value.length ? undefined : placeholder} autoComplete="off" autoCapitalize="characters" spellCheck={false}
        aria-label={label} aria-invalid={invalid || undefined} aria-describedby={[message ? messageId : "", describedBy ?? ""].filter(Boolean).join(" ") || undefined}
        onChange={(event) => { setText(event.target.value); if (message) setMessage(""); }} onKeyDown={onKeyDown} onPaste={onPaste} onBlur={() => { if (text.trim()) enter(text); }}
        className={cn("min-w-24 flex-1 bg-transparent py-0.5 font-mono text-small text-ink outline-none placeholder:font-sans placeholder:text-muted-foreground", invalid && "text-danger")} />
    </div>
    <p id={messageId} role="status" data-testid={testid ? `${testid}-message` : undefined} className={cn("min-h-0 text-small", invalid ? "text-danger" : "text-muted-foreground")}>{message}</p>
  </div>;
}
