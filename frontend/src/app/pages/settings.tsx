import { useEffect } from "react";
import { useParams } from "react-router";
import { SettingsPage } from "../settings/SettingsPage";
import { Tx } from "../../i18n";
import { useWorkspace } from "../workspace";

// Where each settings address scrolls to on the one page that still holds them all (P8.2 splits it).
const CARD_FOR_SECTION: Record<string, string> = {
  notifications: '[aria-labelledby="telegram-bind-title"]',
  appearance: '[aria-labelledby="appearance-title"]',
  data: '.chat-archive-settings',
};

/** /settings/models|notifications|appearance|data|account: all five show the whole settings page for now. */
export function SettingsRoute() {
  const ws = useWorkspace();
  const section = useParams().section ?? "models";
  useEffect(() => {
    const selector = CARD_FOR_SECTION[section];
    const target = selector ? document.querySelector<HTMLElement>(selector) : null;
    if (target) target.scrollIntoView({ block: "start" });
  }, [section]);
  // The footer statement the old shell printed under every page lives here now (P8.2 moves it to 「设置 → 账户 → 关于」).
  // data-slot: this is new markup inside the old page's marker, so the old-UI restore rules skip it.
  return <>
    <SettingsPage onBack={() => ws.go("agent")} />
    <p data-slot="about-note" className="mx-auto max-w-5xl px-5 pt-4 pb-8 text-small text-muted-foreground"><Tx text="FinBot · 本地研究记录 · 研究判断可追溯到原始来源" /></p>
  </>;
}
