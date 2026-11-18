import { useRef, useState, type KeyboardEvent } from "react";
import { StatefulButton } from "@/components/state/StatefulButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorReason } from "@/components/state/error-message";
import { useLocale } from "../../i18n";
import { formatMoney, parseAmount } from "../../portfolio-items.mjs";

/**
 * 可用资金, edited where it stands: 修改 turns the number into an input; Enter or 保存 sends it, Esc or 取消 puts the old number back and sends nothing.
 * The rule is the old page's: a number (a leading minus is allowed: the server flags a negative balance itself, it does not refuse it).  A refusal
 * (not a number) and a failed request are said right under the input.  The tile's own frame is StatTile's, so this is only its value and footnote.
 */
export function CashTile({ funds, onSave }: { funds: string; onSave: (value: string) => Promise<unknown> }) {
  const { t } = useLocale();
  const [draft, setDraft] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  const [saving, setSaving] = useState(false);
  const opener = useRef<HTMLButtonElement>(null), saveButton = useRef<HTMLButtonElement>(null);
  const editing = draft !== null;
  const close = () => { setDraft(null); setProblem(""); requestAnimationFrame(() => opener.current?.focus()); };
  const save = () => {
    if (draft === null || saving) return;
    const value = parseAmount(draft, { allowNegative: true });
    if (value === null) { setProblem(t("金额要填数字。")); return; }
    setProblem(""); setSaving(true);
    return onSave(value).then(close, error => { setProblem(errorReason(error, t)); throw error; }).finally(() => setSaving(false));
  };
  // Enter in the input presses 保存 (so the button shows the progress too); Esc anywhere in the editor cancels.  (Phrasing content only: the tile's value slot is a paragraph, so no form element here.)
  const keys = (event: KeyboardEvent) => {
    if (event.key === "Escape" && !saving) { event.stopPropagation(); close(); }
    if (event.key === "Enter" && (event.target as HTMLElement).tagName === "INPUT") { event.preventDefault(); saveButton.current?.click(); }
  };
  if (!editing) return <span className="flex flex-wrap items-baseline gap-x-2">
    <span data-testid="cash-value">{formatMoney(funds)}</span>
    <Button ref={opener} type="button" variant="link" size="xs" data-testid="cash-edit" className="h-6 px-0 text-small" onClick={() => setDraft(formatMoney(funds).replace(/,/g, ""))}>{t("修改")}</Button>
  </span>;
  return <span role="group" aria-label={t("可用资金")} data-testid="cash-form" className="flex min-w-0 flex-col gap-1.5" onKeyDown={keys}>
    <Input autoFocus data-testid="cash-input" type="text" inputMode="decimal" autoComplete="off" aria-label={t("可用资金")} value={draft} disabled={saving}
      aria-invalid={problem ? true : undefined} aria-describedby={problem ? "cash-problem" : undefined} className="h-9 font-mono text-body tabular-nums max-sm:h-11"
      onChange={event => { setDraft(event.target.value); setProblem(""); }} />
    <span className="flex flex-wrap gap-1.5">
      <StatefulButton ref={saveButton} type="button" size="sm" data-testid="cash-save" className="max-sm:h-11" onClick={save}>{t("保存")}</StatefulButton>
      <Button type="button" size="sm" variant="outline" className="max-sm:h-11" disabled={saving} onClick={close}>{t("取消")}</Button>
    </span>
    {problem && <span id="cash-problem" role="alert" data-testid="cash-problem" className="text-caption font-sans font-normal text-danger">{problem}</span>}
  </span>;
}
