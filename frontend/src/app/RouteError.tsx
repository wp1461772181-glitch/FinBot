import { isRouteErrorResponse, useRouteError } from "react-router";
import { ErrorBar } from "@/components/state/ErrorBar";
import { useLocale } from "../i18n";

/**
 * What stands in a page's place when it cannot be shown: most often a chunk that did not load (offline, or the site
 * was updated after this tab opened and the file it asks for is gone).  The shell around it stays; the reader can
 * reload.  It is the same error bar every block uses (design 4.0, 局部错误), neutral and without an alarm colour: nothing
 * was lost, the page just did not arrive.  重试 reloads the page.
 * It renders above the old-UI marker (the router wraps only the pages in it), so it gets the new base styles.
 */
export function RouteError() {
  const { t } = useLocale();
  const error = useRouteError();
  const detail = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "";
  return (
    <div data-slot="route-error" className="mx-auto flex max-w-xl flex-col gap-2 p-6">
      <ErrorBar message={`${t("页面加载失败")}：${t("网络中断，或站点刚刚更新过。重新加载后再试。")}`} onRetry={() => window.location.reload()} />
      {detail && <p className="px-1 font-mono text-caption break-all text-faint">{detail}</p>}
    </div>
  );
}
