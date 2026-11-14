// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { Suspense, lazy, useState } from "react";
import { useLocale } from "../../i18n";
import { applyTheme, saveTheme, storedTheme, type ThemeChoice } from "../../theme.mjs";

// Radix Select is heavy (about 40 kB gzip); the settings page loads it on demand instead of the main bundle carrying it.
const UpdownSelect = lazy(() => import("@/components/UpdownSelect").then((module) => ({ default: module.UpdownSelect })));

export /** 外观 and 语言 live here (moved out of the topbar); storage keys and behaviour are unchanged. */
function AppearanceCard(){
 const {t,locale,setLocale}=useLocale();
 const [theme,setTheme]=useState<ThemeChoice>(()=>storedTheme());
 return <section className="agent-settings-card appearance-settings" aria-labelledby="appearance-title">
  <h2 id="appearance-title">{t("外观")}</h2>
  <label htmlFor="theme">{t("外观")}
   <select id="theme" value={theme} onChange={event=>{const choice=saveTheme(event.target.value as ThemeChoice);setTheme(choice);applyTheme(choice);}}>
    <option value="light">{t("浅色")}</option><option value="dark">{t("深色")}</option><option value="system">{t("跟随系统")}</option>
   </select></label>
  <Suspense fallback={<div aria-hidden="true" style={{minHeight:68}}/>}><UpdownSelect/></Suspense>
  <h2>{t("语言")}</h2>
  <label htmlFor="locale">{t("语言")}
   <select id="locale" value={locale} onChange={event=>setLocale(event.target.value as "zh-CN"|"en-US")}>
    <option value="zh-CN">中文</option><option value="en-US">English</option>
   </select></label>
 </section>;
}
