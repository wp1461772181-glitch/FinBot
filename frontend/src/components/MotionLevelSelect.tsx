// The animation strength on the settings page (design 4.12 / 6.9 P9): 完整 / 精简 / 关闭, kept in this browser.  A new control embedded in the old
// appearance card (like UpdownSelect), loaded on demand.  The system's reduced-motion setting wins: then the level is 关闭 and cannot be set stronger.
// A hand-picked level beats the automatic ones (the device, the drop after slow frames); `恢复自动` forgets the pick.
import { useSyncExternalStore } from "react";
import { useLocale } from "../i18n";
import { LEVELS, getMotion, subscribeMotion } from "../motion-store.mjs";
import { activateMotion, chooseMotion } from "../motion-control.mjs";
import type { MotionLevel } from "../motion-level.mjs";
import { Segmented } from "./Segmented";

activateMotion(); // the device and the slow-frame drop are part of what this control reports

const NAMES: Record<MotionLevel, string> = { full: "完整动画", lite: "精简动画", off: "关闭动画" };
const HINTS: Record<MotionLevel, string> = { full: "全部效果。", lite: "没有头像光环和交接转环，对话页头部的头像 30 帧。", off: "动效全部静止，状态靠样子和文字区分。" };

export function MotionLevelSelect() {
  const { t } = useLocale();
  const { level, source } = useSyncExternalStore(subscribeMotion, getMotion);
  const system = source === "system";
  const current = source === "system" ? t("关闭（跟随系统设置）")
    : source === "auto-device" ? t("精简（已为这台设备自动选择）")
      : source === "auto-runtime" ? t("精简（本次访问已自动降档）")
        : source === "user" ? t(NAMES[level]) : t("完整（默认）");
  return (
    <div data-slot="motion-level" data-level={level} data-source={source} className="grid gap-2">
      <Segmented<MotionLevel> name="motion-level" testid="motion-level-choice" legend={t("动画强度")} value={level} onChange={(next) => { chooseMotion(next); }}
        options={LEVELS.map((value: MotionLevel) => ({ value, label: t(NAMES[value]), disabled: system && value !== "off" }))} />
      <ul className="m-0 grid list-none gap-0.5 p-0 text-small text-muted-foreground">
        {LEVELS.map((value: MotionLevel) => <li key={value}><span className="font-medium text-ink">{t(NAMES[value])}</span> · {t(HINTS[value])}</li>)}
      </ul>
      <p role="status" data-testid="motion-level-current" className="m-0 text-small text-ink">{t("当前")}：{current}</p>
      {system && <p data-testid="motion-level-system" className="m-0 text-small text-muted-foreground">{t("系统开了「减少动效」，所以这里固定为关闭；站内选项只能更弱，不能更强。")}</p>}
      {source === "user" && !system && (
        <button type="button" data-testid="motion-level-auto" onClick={() => { chooseMotion(null); }}
          className="w-fit cursor-pointer rounded-sm border border-line bg-surface px-2.5 py-1 text-small text-ink max-sm:min-h-11 hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
          {t("恢复自动")}
        </button>
      )}
      <p className="m-0 text-small text-muted-foreground">{t("动画强度只保存在这台设备的这个浏览器里。")}</p>
    </div>
  );
}
