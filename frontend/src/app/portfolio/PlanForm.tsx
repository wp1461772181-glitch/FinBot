import { useState } from "react";
import { StatefulButton } from "@/components/state/StatefulButton";
import { StatusBadge } from "@/components/StatusBadge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorReason } from "@/components/state/error-message";
import { useLocale } from "../../i18n";
import { planBody, type PortfolioPlanForm } from "../../portfolio-items.mjs";

const PRICES: Array<{ key: "add_price" | "stop_price" | "target_price"; label: string }> = [
  { key: "add_price", label: "补仓价" }, { key: "stop_price", label: "止损价" }, { key: "target_price", label: "目标价" },
];
const label = "flex min-w-0 flex-col gap-1.5 text-small font-medium text-ink";

/**
 * 我的计划: the reader's own words and three prices, saved as they are.  Nothing here judges the plan or reminds the reader to act on it.  The draft lives
 * in the page (not in this form), so closing the row and opening it again finds the edit still there, marked 未保存 until it is saved.  The rules are the old
 * form's: a price is a number that is not negative, or blank for "none" (sent as null); the save key is on only when something differs from what is saved.
 */
export function PlanForm({ symbol, form, changed, onChange, onSave }: {
  symbol: string; form: PortfolioPlanForm; changed: boolean;
  onChange: (next: PortfolioPlanForm) => void;
  onSave: (body: NonNullable<Extract<ReturnType<typeof planBody>, { body: unknown }>["body"]>) => Promise<unknown>;
}) {
  const { t } = useLocale();
  const [problem, setProblem] = useState("");
  const set = (key: keyof PortfolioPlanForm, value: string) => { setProblem(""); onChange({ ...form, [key]: value }); };
  const save = () => {
    const built = planBody(form);
    if ("error" in built) { setProblem(t(built.error)); return; }
    setProblem("");
    return onSave(built.body).catch(error => { setProblem(errorReason(error, t)); throw error; });
  };
  return <form data-testid="pf-plan" aria-label={`${symbol} ${t("计划")}`} noValidate className="flex min-w-0 flex-col gap-3" onSubmit={event => event.preventDefault()}>
    <label className={label}>{t("我的计划")}
      <Textarea data-testid="pf-plan-text" rows={3} maxLength={2000} value={form.plan_text} placeholder={t("例如：跌到补仓价分两次补，破止损价就走")} onChange={event => set("plan_text", event.target.value)} />
    </label>
    <div className="grid grid-cols-3 gap-2 max-sm:gap-1.5">
      {PRICES.map(price => <label key={price.key} className={label}>{t(price.label)}
        <Input data-testid={`pf-${price.key}`} type="text" inputMode="decimal" autoComplete="off" value={form[price.key]} className="font-mono tabular-nums max-sm:h-11" onChange={event => set(price.key, event.target.value)} />
      </label>)}
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <StatefulButton type="submit" variant="outline" size="sm" data-testid="pf-plan-save" disabled={!changed} className="max-sm:h-11" onClick={save}>{t("保存计划")}</StatefulButton>
      {changed && <StatusBadge kind="neutral">{t("未保存")}</StatusBadge>}
    </div>
    {problem && <p role="alert" data-testid="pf-plan-problem" className="text-caption text-danger">{problem}</p>}
  </form>;
}
