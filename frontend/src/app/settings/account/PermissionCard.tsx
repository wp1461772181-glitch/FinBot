import { useRef, useState } from "react";
import { ErrorBar } from "@/components/state/ErrorBar";
import { notify } from "@/components/state/notify";
import { Segmented } from "@/components/Segmented";
import { getPermissionMode, putPermissionMode, type PermissionMode } from "../../../api/permission-mode";
import { useLocale } from "../../../i18n";
import { useLoad } from "../../use-load";
import { SettingsCard } from "../SettingsCard";

const WHAT: Record<PermissionMode, string> = {
  ask: "每一个会写东西的操作都先放进确认卡，你点了才执行，连记一条偏好也一样。",
  default: "查资料、拉取官方公开资料（SEC 原文、价格历史）、记偏好、加减研究队列直接做；把网页存进资料库、记交易、改计划、建例行任务、改设置，以及发起预测、删除这类花钱或不可撤销的，放进确认卡等你点。",
  full: "所有操作直接做，不弹确认卡；做完在回答里逐条告诉你做了什么、怎么撤销。",
};

/**
 * 权限 (11-28, owner: 「把选择权交到用户身上」): 每步都问 / 默认 / 完全放行, saved at once (``PUT /agent-chat/permission-mode``).  The two lines below
 * hold in every mode: after it has read a page, news or a filing in a turn, a write such material could ask for waits for your press; keys, logins
 * and trades are never its to do.  In a chat, 「这次不用确认，直接做」 lets one turn run without cards.
 */
export function PermissionCard() {
  const { t } = useLocale();
  const read = useLoad(signal => getPermissionMode(signal));
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);      // Segmented calls back on both change and click: one press must send one write
  const mode = read.data?.mode ?? null;
  async function choose(next: PermissionMode) {
    if (next === mode || busy.current) return;
    busy.current = true;
    setSaving(true);
    try {
      await putPermissionMode(next);
      await read.reload();
      notify.success(t("权限已改为「{label}」，从你的下一条消息起生效。").replace("{label}", t(next === "ask" ? "每步都问" : next === "full" ? "完全放行" : "默认")), { id: "settings:permission" });
    } catch (error) {
      notify.error(error instanceof Error ? error.message : t("保存失败，请重试。"), { id: "settings:permission" });
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }
  return <SettingsCard id="account-permission" title={t("权限")} description={t("它可以替你做多少事、哪些要先问你。")} testid="account-permission">
    {read.error != null && <ErrorBar error={read.error} onRetry={() => void read.reload()} retrying={read.loading} />}
    {mode && <>
      <Segmented<PermissionMode> name="settings-permission" testid="permission-choice" legend={<span className="sr-only">{t("权限")}</span>} value={mode}
        options={[{ value: "ask", label: t("每步都问") }, { value: "default", label: t("默认") }, { value: "full", label: t("完全放行") }]} disabled={saving} onChange={(next) => void choose(next)} />
      <p data-testid="permission-what" className="text-small text-ink-2">{t(WHAT[mode])}</p>
    </>}
    <ul data-testid="permission-always" className="m-0 grid list-disc gap-1 pl-5 text-small text-muted-foreground">
      <li>{t("不论哪一档：它在这一轮读过网页、新闻或申报之后，会改你数据的操作仍放进确认卡，免得被资料里的话支使。")}</li>
      <li>{t("下单交易、填密钥和登录凭证，它永远不做。")}</li>
      <li>{t("对话里说「这次不用确认，直接做」，只对那一轮生效。")}</li>
    </ul>
  </SettingsCard>;
}
