import { useState } from "react";
import { useNavigate } from "react-router";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { setChatMode } from "../../api/base";
import { chatIdentityKeys } from "../../chat-identity.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { applyTheme, saveTheme } from "../../theme.mjs";

export type ModeChange = (mode: "guest" | "personal" | null) => void;

/**
 * The only two ways out of the mode the reader is in (design S5: mode switch and sign-out live in the account menu and
 * nowhere else).  Both go through the same functions the old header used: `setChatMode("guest")` drops the stored login
 * and keeps the guest identity; sign-out also forgets which mode was chosen, so the login page comes back.
 */
export function useAccountActions(onModeChange: ModeChange) {
  const navigate = useNavigate();
  return {
    toGuest() { setChatMode("guest"); onModeChange("guest"); navigate(paths.chat()); },
    signOut() {
      setChatMode("guest");
      try { window.localStorage.removeItem(chatIdentityKeys.mode); } catch { /* the login page shows anyway on the next start */ }
      onModeChange(null);
      navigate(paths.login());
    },
  };
}

/** Light or dark in one press (the full choice, including "follow the system", stays on the settings page). */
export function ThemeToggle({ className }: { className?: string }) {
  const { t } = useLocale();
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  const next = theme === "dark" ? "light" : "dark";
  const Icon = theme === "dark" ? Sun : Moon;
  return <Button type="button" variant="ghost" size="icon" className={className} aria-label={t(theme === "dark" ? "切换到浅色" : "切换到深色")} title={t(theme === "dark" ? "切换到浅色" : "切换到深色")}
    onClick={() => { saveTheme(next); applyTheme(next); setTheme(next); }}>
    <Icon aria-hidden="true" />
  </Button>;
}
