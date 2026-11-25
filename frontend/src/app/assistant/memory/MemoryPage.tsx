import { useSearchParams } from "react-router";
import { CompanyTabs } from "../../research/CompanyTabs";
import { useLocale } from "../../../i18n";
import { OwnerViewsPanel } from "./OwnerViewsPanel";
import { ProfilePanel } from "./ProfilePanel";
import { RecallPanel } from "./RecallPanel";
import { memoryTab } from "./memory-view.mjs";

/**
 * 记忆 (#/assistant/memory, design 4.11): two tabs in the address (?tab=recall is 往事; nothing, or any other value, is 画像), so a refresh stays on the tab.  The tab list is the company page's (manual
 * activation: the arrow keys move the focus, Enter or Space opens).  Each tab holds its own one sentence that says what it is not (a preference is not evidence, a past talk is a clue, not evidence).
 */
export function MemoryPage() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const tab = memoryTab(params.get("tab"));
  const choose = (value: "profile" | "recall") => setParams(previous => { const next = new URLSearchParams(previous); if (value === "recall") next.set("tab", "recall"); else next.delete("tab"); return next; }, { replace: true });
  return <main data-testid="memory-page" aria-labelledby="memory-title" className="mx-auto flex w-full min-w-0 max-w-[1100px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <h1 id="memory-title" className="text-title-m text-ink">{t("记忆")}</h1>
    <CompanyTabs label={t("记忆")} value={tab} onChange={choose} tabs={[{ value: "profile", testId: "tab-profile", label: t("画像") }, { value: "recall", testId: "tab-recall", label: t("往事") }]}>
      {tab === "profile" ? <div className="flex min-w-0 flex-col gap-6"><OwnerViewsPanel /><ProfilePanel /></div> : <RecallPanel />}
    </CompanyTabs>
  </main>;
}
