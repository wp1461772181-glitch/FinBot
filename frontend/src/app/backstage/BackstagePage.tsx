import { useNavigate, useParams } from "react-router";
import { useLocale } from "../../i18n";
import { backstageTab, paths } from "../../routes.mjs";
import { CompanyTabs } from "../research/CompanyTabs";
import { AnswersTab } from "./AnswersTab";
import { DeliveriesTab } from "./DeliveriesTab";
import { DutyTab } from "./DutyTab";
import { OperationsTab } from "./OperationsTab";
import { UsageTab } from "./UsageTab";

/**
 * 后台 (#/backstage/<tab>): the owner's read-only look behind the assistant.  Five tabs in the address (回答, 用量, 操作记录, 提醒投递, 值班).  Nothing on this page writes except the 有用／没用 feedback on duty and brief deliveries: it has
 * no button that changes a record, and every request is a GET that the server answers only to the owner.
 */
export function BackstagePage() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const tab = backstageTab(useParams().tab);
  return <main data-testid="backstage-page" aria-labelledby="backstage-title" className="mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <header className="flex min-w-0 flex-col gap-1">
      <h1 id="backstage-title" className="text-title-m text-ink">{t("后台")}</h1>
      <p className="max-w-2xl text-small text-muted-foreground">{t("助手每次回答是怎么来的、花了多少、提过哪些操作、发过哪些提醒。这里只能看，不能改。")}</p>
    </header>
    <CompanyTabs label={t("后台页签")} value={tab} onChange={value => navigate(paths.backstage(value), { replace: true })} tabs={[
      { value: "answers", testId: "tab-answers", label: t("回答") },
      { value: "usage", testId: "tab-usage", label: t("用量") },
      { value: "operations", testId: "tab-operations", label: t("操作记录") },
      { value: "deliveries", testId: "tab-deliveries", label: t("提醒投递") },
      { value: "duty", testId: "tab-duty", label: t("值班") },
    ]}>
      {tab === "answers" && <AnswersTab />}
      {tab === "usage" && <UsageTab />}
      {tab === "operations" && <OperationsTab />}
      {tab === "deliveries" && <DeliveriesTab />}
      {tab === "duty" && <DutyTab />}
    </CompanyTabs>
  </main>;
}
