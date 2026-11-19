import { useState } from "react";
import { MotionLevelSelect } from "@/components/MotionLevelSelect";
import { Segmented } from "@/components/Segmented";
import { useLocale } from "../../../i18n";
import { applyTheme, saveTheme, storedTheme, type ThemeChoice } from "../../../theme.mjs";
import { applyUpdown, saveUpdown, storedUpdown, type UpdownChoice } from "../../../updown.mjs";
import { SettingsCard } from "../SettingsCard";

/**
 * 外观 (#/settings/appearance, design 4.12): theme, language, the up / down colours and the animation strength, each a row of choices that takes effect and is kept at once.
 * Nothing is sent to the server; the storage keys and the <html> attributes are the old page's (saveTheme + applyTheme, saveUpdown + applyUpdown, setLocale).
 */
export function AppearancePage() {
  const { t, locale, setLocale } = useLocale();
  const [theme, setTheme] = useState<ThemeChoice>(() => storedTheme());
  const [updown, setUpdown] = useState<UpdownChoice>(() => storedUpdown());
  return <div data-testid="settings-appearance-body" className="flex flex-col gap-5">
    <SettingsCard id="appearance-theme" title={t("主题")} testid="appearance-theme">
      <Segmented<ThemeChoice> name="settings-theme" testid="appearance-theme-choice" legend={<span className="sr-only">{t("主题")}</span>} value={theme}
        options={[{ value: "light", label: t("浅色") }, { value: "dark", label: t("深色") }, { value: "system", label: t("跟随系统") }]}
        onChange={(choice) => { const saved = saveTheme(choice); setTheme(saved); applyTheme(saved); }} />
    </SettingsCard>
    <SettingsCard id="appearance-locale" title={t("语言")} testid="appearance-locale">
      <Segmented<"zh-CN" | "en-US"> name="settings-locale" testid="appearance-locale-choice" legend={<span className="sr-only">{t("语言")}</span>} value={locale}
        options={[{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }]} onChange={(choice) => setLocale(choice)} />
    </SettingsCard>
    <SettingsCard id="appearance-updown" title={t("涨跌配色")} description={t("只换涨和跌两种颜色；成功与出错的颜色不变。")} testid="appearance-updown">
      <Segmented<UpdownChoice> name="settings-updown" testid="appearance-updown-choice" legend={<span className="sr-only">{t("涨跌配色")}</span>} value={updown}
        options={[{ value: "green-up", label: t("绿涨红跌") }, { value: "red-up", label: t("红涨绿跌") }]}
        onChange={(choice) => { const saved = saveUpdown(choice); setUpdown(saved); applyUpdown(saved); }} />
    </SettingsCard>
    <SettingsCard id="appearance-motion" title={t("动画")} testid="appearance-motion"><MotionLevelSelect /></SettingsCard>
  </div>;
}
