import { useState } from "react";
import { confirm } from "@/components/state/confirm";
import { errorReason } from "@/components/state/error-message";
import { notify } from "@/components/state/notify";
import { deleteAgentTask, updateAgentTask, type AgentTask } from "../../api/tasks";
import { useLocale } from "../../i18n";

/**
 * The two things a task card does by itself: the switch (saved as it is flipped; a failure puts the switch back and says so) and 删除 (the old question, press and
 * hold).  The requests are the old page's: PATCH {enabled} and DELETE.  `after` reads the lists again (and tells the app the bot list may have moved).
 */
export function useTaskActions(after: () => Promise<unknown> | void) {
  const { t } = useLocale();
  const [busy, setBusy] = useState<string | null>(null);
  /** The switch as the reader flipped it, until the server has answered. */
  const [flipped, setFlipped] = useState<Record<string, boolean>>({});

  async function toggle(task: AgentTask, enabled: boolean) {
    setFlipped(current => ({ ...current, [task.id]: enabled })); setBusy(task.id);
    try { await updateAgentTask(task.id, { enabled }); await after(); }
    catch (error) { notify.error(errorReason(error, t), { id: `routines:toggle:${task.id}` }); }
    finally { setFlipped(({ [task.id]: _gone, ...rest }) => rest); setBusy(null); }
  }
  async function remove(task: AgentTask, returnFocus?: HTMLElement | null) {
    // The question is asked from a menu item that is gone when it closes; the focus goes back to the card's 「…」 button.
    const yes = await confirm({ ...(returnFocus ? { returnFocus } : {}), title: t("删除这个任务？"), description: t("已生成的简报会保留，这个任务之后不再运行。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (!yes) return;
    setBusy(task.id);
    try { await deleteAgentTask(task.id); await after(); notify.success(t("任务已删除。"), { id: "routines:deleted" }); }
    catch (error) { notify.error(errorReason(error, t), { id: `routines:delete:${task.id}` }); }
    finally { setBusy(null); }
  }
  return { busy, flipped, toggle, remove };
}
