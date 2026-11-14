import { Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLocale } from "../../i18n";
import { openLoginDialog } from "./login-events";

/** What a page the owner alone can use shows to someone browsing read-only: one plain notice and the way in (not a blank page, not an error bar). */
export function NeedLogin() {
  const { t } = useLocale();
  return <section data-slot="need-login" aria-labelledby="need-login-title" className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
    <span className="grid size-11 place-items-center rounded-full bg-sunken text-muted-foreground"><Lock aria-hidden="true" className="size-5" /></span>
    <h2 id="need-login-title" className="text-title-s text-ink">{t("需要登录")}</h2>
    <p className="text-body text-muted-foreground">{t("这一页只对登录后的个人账户开放。现在是只读浏览，可以看研究页面，但看不到你的 bot、持仓和任务。")}</p>
    <Button type="button" onClick={() => openLoginDialog(true)}>{t("登录")}</Button>
  </section>;
}
