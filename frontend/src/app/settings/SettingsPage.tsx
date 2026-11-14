// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useState } from "react";
import { getChatMode } from "../../api";
import { useLocale } from "../../i18n";
import { KnowledgeAdminPage } from "../../KnowledgeAdminPage";
import { AppearanceCard } from "./AppearanceCard";
import { MaterialAnalysisDefaultCard } from "./MaterialAnalysisDefaultCard";
import { TelegramBindCard } from "./TelegramBindCard";
import { PushoverCard } from "./PushoverCard";
import { ChatArchiveSettings } from "./ChatArchiveSettings";
import { ModelCatalogCard } from "./ModelCatalogCard";

export function SettingsPage({ onBack }: { onBack: () => void }) {
 const {t}=useLocale();const [knowledgeTab,setKnowledgeTab]=useState(false);
 if(knowledgeTab)return <KnowledgeAdminPage onBack={()=>setKnowledgeTab(false)}/>;
 // UX batch 3: models are configured only in the server catalog (ModelCatalogCard); the browser model profiles,
 // their import/export and the separate 后台任务模型 card are gone (tasks use the bot's catalog model or the default).
 return <main className="workspace agent-admin" aria-labelledby="agent-admin-title"><header className="workspace-heading"><div><p className="eyebrow">FinBot / {t("后台设置")}</p><h1 id="agent-admin-title">{t("模型连接设置")}</h1></div><div className="agent-header-actions"><button type="button" className="secondary-action" onClick={()=>setKnowledgeTab(true)}>研究知识库</button><button type="button" className="secondary-action" onClick={onBack}>{t("返回 Agent 对话")}</button></div></header>
  {getChatMode()!=="personal"&&<section className="agent-settings-card"><p>{t("登录个人聊天后才能配置模型：对话、bot 和定时任务都用服务器模型目录里的模型。")}</p></section>}
  <AppearanceCard/><ModelCatalogCard/><MaterialAnalysisDefaultCard/><ChatArchiveSettings/><TelegramBindCard/><PushoverCard/></main>;
}
