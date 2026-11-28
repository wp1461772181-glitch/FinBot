import { useLocale } from "../../../i18n";
import { useWorkspace } from "../../workspace";
import { SettingsCard } from "../SettingsCard";
import { PermissionCard } from "./PermissionCard";
import { version } from "../../../../package.json";

/**
 * 账户 (#/settings/account, design 4.12): the mode the app is in, and 关于 (the version, the statement the old shell printed under every page, the third-party notices).
 * Switching the mode and signing out are in the sidebar's account menu (on a phone, in 「更多」) and nowhere else (design S5, 3.4; ruling opus-p82-ruling 2026-11-19): this page only says where.
 * The picture is the brand mark's still pose (public/logo.svg; the login page's BrandLogo would pull orb.mjs out of the chat chunk into the first screen).
 * The notices' words follow THIRD_PARTY_NOTICES.md at the repository root and the first line of styles/fonts.css.
 */
export function AccountPage() {
  const { t } = useLocale();
  const { personal } = useWorkspace();
  return <div data-testid="settings-account-body" className="flex flex-col gap-5">
    <SettingsCard id="account-mode" title={t("当前模式")} testid="account-mode">
      <p data-testid="account-mode-name" className="text-body font-medium text-ink">{personal ? t("个人模式") : t("访客只读")}</p>
      <p className="text-small text-muted-foreground">{t("切换模式和登出都在侧栏底部的账户菜单里；手机上在「更多」里。")}</p>
    </SettingsCard>
    {personal && <PermissionCard />}
    <SettingsCard id="account-about" title={t("关于")} testid="account-about">
      <div className="flex items-center gap-4">
        <img src={`${import.meta.env.BASE_URL}logo.svg`} alt="" aria-hidden="true" data-testid="account-logo" className="size-16 shrink-0 object-contain" />
        <dl className="m-0 grid gap-1 text-small">
          <div className="flex gap-2"><dt className="text-muted-foreground">{t("版本")}</dt><dd data-testid="account-version" className="m-0 font-mono text-ink">{version}</dd></div>
        </dl>
      </div>
      <p data-testid="about-note" className="text-small text-ink-2">{t("FinBot · 本地研究记录 · 研究判断可追溯到原始来源")}</p>
      <div data-testid="account-notices" className="flex flex-col gap-1.5">
        <h3 className="text-body font-medium text-ink">{t("第三方声明")}</h3>
        <ul className="m-0 grid list-none gap-1.5 p-0 text-small text-ink-2">
          <li data-testid="notice-bloub">{t("Bloub 动画引擎（bot 头像的动画）：MIT 许可，Copyright (c) 2026 Jérémy Perret。")}</li>
          <li data-testid="notice-fonts">{t("自带字体 Inter、JetBrains Mono、Source Serif 4：SIL Open Font License 1.1（OFL-1.1）。")}</li>
        </ul>
      </div>
    </SettingsCard>
  </div>;
}
