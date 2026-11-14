// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useRef } from "react";
import { useLocale } from "../../i18n";
import { useChat } from "../chat/ChatSessionProvider";

export function ChatArchiveSettings(){
 const {t}=useLocale(),c=useChat(),input=useRef<HTMLInputElement>(null);
 return <section className="chat-archive-settings"><h2>{t("本地对话归档")}</h2><p>{t("归档仅供本地只读查看，不会作为模型上下文发送。")}</p><div className="chat-archive-tools"><button className="secondary-action" onClick={()=>void c.connectFile()}>{t("连接自动保存文件")}</button>{c.fileName&&<><span>{c.fileName}</span><button className="secondary-action" onClick={c.disconnectFile}>{t("断开")}</button></>}<button className="secondary-action" onClick={c.exportArchive}>{t("导出 JSON")}</button><button className="secondary-action" onClick={()=>input.current?.click()}>{t("导入查看")}</button><input ref={input} className="visually-hidden" type="file" accept="application/json,.json" onChange={e=>{const file=e.target.files?.[0];if(file)void c.importArchive(file);e.target.value=""}}/>{c.archiveStatus&&<span role="status">{c.archiveStatus}</span>}</div>{c.archiveView&&<div className="chat-archive-banner"><span>{t("本地归档只读查看；这些内容不会发送给模型，也不是已核验的服务端证据。")}</span><button className="secondary-action" onClick={c.returnLive}>{t("返回当前对话")}</button><label>{t("选择归档对话")}<select value={c.archiveView.id} onChange={e=>c.selectArchive(e.target.value)}>{(c.archive?.conversations??[]).map(item=><option key={item.id} value={item.id}>{new Date(item.updated_at).toLocaleString()} · {item.messages.length}</option>)}</select></label></div>}</section>;
}
