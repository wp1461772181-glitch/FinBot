import { useState } from "react";
import { useSearchParams } from "react-router";
import { ErrorBar } from "@/components/state/ErrorBar";
import { getMemoryOverview } from "../../../api/memory-overview";
import { CompanyTabs } from "../../research/CompanyTabs";
import { useLocale } from "../../../i18n";
import { useLoad } from "../../use-load";
import { MemorySummary } from "./MemorySummary";
import { OwnerViewsPanel } from "./OwnerViewsPanel";
import { ProfilePanel } from "./ProfilePanel";
import { RecallPanel } from "./RecallPanel";
import { RoleTemplatesPanel } from "./RoleTemplatesPanel";
import { SeenBlockFold } from "./SeenBlockFold";
import { WatchPanel } from "./WatchPanel";
import { memoryTab } from "./memory-view.mjs";

/**
 * 它眼中的你 (the 画像 tab): one read of the overview feeds the head, the views and the rest; a part the server could not build (`errors` names it) shows its own error bar with 重试 and
 * the others still show.  The profile section keeps its own load (its own requests, unchanged) and tells this page after a write, so the counts stay true.
 */
function YouTab() {
  const overview = useLoad(signal => getMemoryOverview(signal));
  const data = overview.data;
  const failed = (part: string) => Boolean(data?.errors.includes(part));
  const reload = () => overview.reload();
  // 用模板起步 writes profile items from outside the profile section's own requests: after an apply or an undo the section is read again (a new key), and the overview re-reads its counts.
  const [profileKey, setProfileKey] = useState(0);
  const templatesChanged = () => { setProfileKey(key => key + 1); void overview.reload(); };
  // The order is the plan's: head, his views, the profile (its own load), what it watches, what the model reads.  When the whole read failed there is nothing to show for the parts that
  // come from it (the bar above says so, with 重试); the profile section does not depend on it and stays.
  const read = data !== null || overview.loading;
  return <div className="flex min-w-0 flex-col gap-6">
    {overview.error != null && <ErrorBar error={overview.error} onRetry={() => void overview.reload()} retrying={overview.loading} />}
    <MemorySummary counts={data?.counts ?? null} jobs={data?.jobs ?? null} countsFailed={failed("counts")} jobsFailed={failed("jobs")} loading={overview.loading} onReload={reload} />
    <RoleTemplatesPanel onChanged={templatesChanged} />
    {read && <OwnerViewsPanel views={data?.views ?? null} failed={failed("views")} loading={overview.loading} onReload={reload} />}
    <ProfilePanel key={profileKey} onChanged={() => void overview.reload()} />
    {read && <WatchPanel watch={data?.watch ?? null} failed={failed("watch")} loading={overview.loading} onReload={reload} />}
    {read && <SeenBlockFold text={data?.seen_block ?? null} failed={failed("seen_block")} loading={overview.loading} onReload={reload} />}
  </div>;
}

/**
 * 记忆 (#/assistant/memory, design 4.11): two tabs in the address (?tab=recall is 往事; nothing, or any other value, is 它眼中的你, the old 画像 under its new name), so a refresh stays on the tab.  The tab list is the company page's (manual
 * activation: the arrow keys move the focus, Enter or Space opens).  Each tab holds its own one sentence that says what it is not (a preference is not evidence, a past talk is a clue, not evidence).
 */
export function MemoryPage() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const tab = memoryTab(params.get("tab"));
  const choose = (value: "profile" | "recall") => setParams(previous => { const next = new URLSearchParams(previous); if (value === "recall") next.set("tab", "recall"); else next.delete("tab"); return next; }, { replace: true });
  return <main data-testid="memory-page" aria-labelledby="memory-title" className="mx-auto flex w-full min-w-0 max-w-[1100px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <h1 id="memory-title" className="text-title-m text-ink">{t("记忆")}</h1>
    <CompanyTabs label={t("记忆")} value={tab} onChange={choose} tabs={[{ value: "profile", testId: "tab-profile", label: t("它眼中的你") }, { value: "recall", testId: "tab-recall", label: t("往事") }]}>
      {tab === "profile" ? <YouTab /> : <RecallPanel />}
    </CompanyTabs>
  </main>;
}
