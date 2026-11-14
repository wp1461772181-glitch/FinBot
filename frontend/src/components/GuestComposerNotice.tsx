import { Button } from "@/components/ui/button";
import { useLocale } from "../i18n";
import { openLoginDialog } from "../app/shell/login-events";

/** What stands in the chat's input area for someone browsing read-only (design S14): the way in, not a box that cannot send. */
export function GuestComposerNotice() {
  const { t } = useLocale();
  return <div data-slot="guest-composer" className="mx-auto flex w-full flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3">
    <p className="text-body text-ink-2">{t("登录后可以对话")}</p>
    <Button type="button" onClick={() => openLoginDialog(true)}>{t("登录")}</Button>
  </div>;
}
