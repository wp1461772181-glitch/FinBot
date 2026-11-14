import { useEffect } from "react";
import { useParams } from "react-router";
import { AgentAdminPage } from "../../AgentChatPanel";
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
  return <AgentAdminPage onBack={() => ws.go("agent")} />;
}
