import { isRouteErrorResponse, useRouteError } from "react-router";
import { useLocale } from "../i18n";

/**
 * What stands in a page's place when it cannot be shown: most often a chunk that did not load (offline, or the site
 * was updated after this tab opened and the file it asks for is gone).  The shell around it stays; the reader can
 * reload.  It is deliberately plain and neutral (no alarm colour): nothing was lost, the page just did not arrive.
 * Its one button is a plain element rather than the shadcn Button: this file is in the first load, and Button brings tailwind-merge with it.
 * data-slot keeps the old-UI restore block off it: it is new markup inside the data-legacy tree.
 */
export function RouteError() {
  const { t } = useLocale();
  const error = useRouteError();
  const detail = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "";
  return (
    <div data-slot="route-error" role="alert" className="mx-auto flex max-w-md flex-col items-start gap-3 p-8">
      <h2 className="text-lg font-semibold text-ink">{t("页面加载失败")}</h2>
      <p className="text-muted-foreground">{t("网络中断，或站点刚刚更新过。重新加载后再试。")}</p>
      {detail && <p className="text-caption font-mono text-faint break-all">{detail}</p>}
      <button type="button" className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" onClick={() => window.location.reload()}>{t("重新加载")}</button>
    </div>
  );
}
