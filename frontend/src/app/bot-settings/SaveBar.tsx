import { Button } from "@/components/ui/button";
import { StatefulButton } from "@/components/state/StatefulButton";
import { ErrorBar } from "@/components/state/ErrorBar";
import { useLocale } from "../../i18n";

/**
 * The bar that sticks to the bottom of the page while the form holds a change: 「有未保存的修改 · 放弃 · 保存」.  A failed save puts its reason above the
 * bar (the changes stay); a success is announced by the toast and the bar goes with the changes.  On a phone it sits above the tab bar.
 */
export function SaveBar({ error, canSave, saving, onDiscard, onSave }: { error: string; canSave: boolean; saving: boolean; onDiscard: () => void; onSave: () => Promise<unknown> }) {
  const { t } = useLocale();
  return <div data-slot="save-bar" data-testid="save-bar" role="region" aria-label={t("保存修改")}
    className="sticky bottom-0 z-sticky -mx-4 mt-6 border-t border-line bg-background/95 px-4 py-3 backdrop-blur max-lg:bottom-[calc(3.5rem+env(safe-area-inset-bottom,0px))] lg:-mx-6 lg:px-6">
    <div className="mx-auto flex max-w-[1040px] flex-col gap-2">
      {error && <ErrorBar message={error} />}
      <div className="flex flex-wrap items-center gap-2">
        <p data-testid="save-bar-text" className="min-w-0 flex-1 text-small text-ink">{t("有未保存的修改")}</p>
        <Button type="button" variant="ghost" data-testid="save-bar-discard" disabled={saving} onClick={onDiscard} className="max-md:h-11">{t("放弃")}</Button>
        <StatefulButton type="button" data-testid="save-bar-save" disabled={!canSave} onClick={() => onSave()} className="max-md:h-11">{t("保存")}</StatefulButton>
      </div>
    </div>
  </div>;
}
