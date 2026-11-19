import { lazy, Suspense } from "react";
import { SettingsLayout, type SettingsSection } from "../settings/SettingsLayout";
import { SettingsSkeleton } from "../settings/SettingsSkeleton";

// Each sub page is a chunk of its own, so the appearance page does not carry the model dialog (and the account page does not carry the archive code).
const ModelsPage = lazy(() => import("../settings/models/ModelsPage").then((m) => ({ default: m.ModelsPage })));
const NotificationsPage = lazy(() => import("../settings/notifications/NotificationsPage").then((m) => ({ default: m.NotificationsPage })));
const AppearancePage = lazy(() => import("../settings/appearance/AppearancePage").then((m) => ({ default: m.AppearancePage })));
const DataPage = lazy(() => import("../settings/data/DataPage").then((m) => ({ default: m.DataPage })));
const AccountPage = lazy(() => import("../settings/account/AccountPage").then((m) => ({ default: m.AccountPage })));
const BODY = { models: ModelsPage, notifications: NotificationsPage, appearance: AppearancePage, data: DataPage, account: AccountPage } as const;

/** /settings/models|notifications|appearance|data|account: one page each (P8.2).  The router hands the section in as a prop (the five addresses are literal routes, so there is no :section parameter to read). */
export function SettingsRoute({ section = "models" }: { section?: SettingsSection }) {
  const Body = BODY[section] ?? ModelsPage;
  return <SettingsLayout section={section}><Suspense fallback={<SettingsSkeleton />}><Body /></Suspense></SettingsLayout>;
}
