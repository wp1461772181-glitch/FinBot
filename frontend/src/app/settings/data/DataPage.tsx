import { useRef } from "react";
import { Download, FileUp, Link2, Unlink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLocale } from "../../../i18n";
import { useChat } from "../../chat/ChatSessionProvider";
import { SettingsCard } from "../SettingsCard";

/**
 * 数据 (#/settings/data, design 4.12): the chat's local archive.  Everything is the chat session's own (src/app/chat/ChatSessionProvider.tsx, unchanged): connect a file the page writes to as the chat goes on, export, open an
 * exported file read-only.  No request goes to the server.  Below, where the chat's messages are kept (the sentence the chat header's ⓘ holds).
 */
export function DataPage() {
  const { t } = useLocale();
  const c = useChat();
  const input = useRef<HTMLInputElement>(null);
  const view = c.archiveView;
  return <div data-testid="settings-data-body" className="flex flex-col gap-5">
    <SettingsCard id="data-archive" title={t("本地对话归档")} description={t("归档仅供本地只读查看，不会作为模型上下文发送。")} testid="archive-card">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" data-testid="archive-connect" className="max-sm:h-11" onClick={() => void c.connectFile()}><Link2 aria-hidden="true" />{t("连接自动保存文件")}</Button>
        {c.fileName && <>
          <span data-testid="archive-file" className="min-w-0 break-all font-mono text-small text-ink-2">{c.fileName}</span>
          <Button type="button" variant="outline" data-testid="archive-disconnect" className="max-sm:h-11" onClick={c.disconnectFile}><Unlink aria-hidden="true" />{t("断开")}</Button>
        </>}
        <Button type="button" variant="outline" data-testid="archive-export" className="max-sm:h-11" onClick={c.exportArchive}><Download aria-hidden="true" />{t("导出 JSON")}</Button>
        <Button type="button" variant="outline" data-testid="archive-import" className="max-sm:h-11" onClick={() => input.current?.click()}><FileUp aria-hidden="true" />{t("导入查看")}</Button>
        <input ref={input} type="file" hidden accept="application/json,.json" data-testid="archive-file-input" onChange={(e) => { const file = e.target.files?.[0]; if (file) void c.importArchive(file); e.target.value = ""; }} />
      </div>
      {c.archiveStatus && <p role="status" data-testid="archive-status" className="text-small text-ink">{c.archiveStatus}</p>}
      {view && <div data-testid="archive-view" className="flex flex-col gap-3 rounded-md border border-line bg-sunken p-3">
        <p className="text-small text-ink-2">{t("本地归档只读查看；这些内容不会发送给模型，也不是已核验的服务端证据。")}</p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            <span id="archive-pick-label" className="text-small font-medium text-ink">{t("选择归档对话")}</span>
            <Select value={view.id} onValueChange={(id) => c.selectArchive(id)}>
              <SelectTrigger aria-labelledby="archive-pick-label" data-testid="archive-pick" className="w-72 max-w-full max-sm:h-11"><SelectValue /></SelectTrigger>
              <SelectContent>{(c.archive?.conversations ?? []).map((item) => <SelectItem key={item.id} value={item.id}>{new Date(item.updated_at).toLocaleString()} · {item.messages.length}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <Button type="button" variant="outline" data-testid="archive-return" className="max-sm:h-11" onClick={c.returnLive}>{t("返回当前对话")}</Button>
        </div>
      </div>}
    </SettingsCard>
    <SettingsCard id="data-where" title={t("数据去向")} testid="data-where">
      <p className="text-small text-ink-2">{t("消息和研究工具轨迹会保存到服务端；工具按权限读取资料并执行明确请求的系统任务。")}</p>
    </SettingsCard>
  </div>;
}
