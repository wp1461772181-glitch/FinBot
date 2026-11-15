import { useEffect, useRef } from "react";
import { useBlocker } from "react-router";
import { confirm } from "@/components/state/confirm";
import { useLocale } from "../../i18n";

/**
 * A change that is not saved must not be lost by leaving the page without a word (S6).  A move to another page of the app is held by the router's
 * blocker and the reader is asked (放弃修改并离开 / 留下); closing the tab or reloading goes through the browser's own `beforeunload` question.
 * A move that keeps the page (the section in the address) is not a leave.  `allowLeave.current = true` lets one move through (after a delete).
 */
export function useLeaveGuard(dirty: boolean) {
  const { t } = useLocale();
  const allowLeave = useRef(false);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !allowLeave.current && currentLocation.pathname !== nextLocation.pathname);
  const asking = useRef(false);
  useEffect(() => {
    if (blocker.state !== "blocked" || asking.current) return;
    asking.current = true;
    void confirm({ title: t("放弃未保存的修改？"), description: t("离开这一页会丢掉还没保存的修改。"), confirmLabel: t("放弃修改并离开"), cancelLabel: t("留下"), tone: "danger" })
      .then((leave) => { if (leave) blocker.proceed?.(); else blocker.reset?.(); })
      .finally(() => { asking.current = false; });
  }, [blocker, t]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return { allowLeave };
}
