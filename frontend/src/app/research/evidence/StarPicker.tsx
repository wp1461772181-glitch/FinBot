import { Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale } from "../../../i18n";

/** The reader's own credibility for the source, 1–5 stars (native radios: arrow keys move, the group has a name).  A judgment of the source, not a probability. */
export function StarPicker({ value, onChange, name, disabled }: { value: number; onChange: (value: number) => void; name: string; disabled?: boolean }) {
  const { t } = useLocale();
  return <fieldset data-testid="upload-stars" disabled={disabled} className="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0">
    <legend className="mb-1 p-0 text-small font-medium text-ink">{t("用户评估的消息可信度")}</legend>
    <div className="flex items-center gap-1">
      {[1, 2, 3, 4, 5].map(n => <label key={n} title={`${n} ${t("星")}`} className={cn("relative inline-flex size-9 cursor-pointer items-center justify-center rounded-sm has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring max-sm:size-11", n <= value ? "text-ink" : "text-line-strong", disabled && "cursor-not-allowed")}>
        <input type="radio" name={name} value={n} checked={value === n} onChange={() => onChange(n)} className="sr-only" />
        <Star aria-hidden="true" className={cn("size-6", n <= value && "fill-current")} /><span className="sr-only">{n} {t("星")}</span>
      </label>)}
      <span className="ml-2 font-mono text-small text-ink-2">{value} / 5</span>
    </div>
    <p className="text-caption text-muted-foreground">{t("记录你的来源判断，不是精确概率，也不代表内容已获官方证实。")}</p>
  </fieldset>;
}
