import { useCallback, useEffect, useState } from "react";
import { getModelCatalog, type BotTemplate, type BotTool, type ModelCatalog } from "../../api/bots";
import { getBotTemplates } from "../../api/bots-admin";
import { message } from "../../bot-message";

/** The catalog, the tool list and the templates a bot's settings need (the same two requests the old 档案 tab made). */
export function useBotOptions() {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null), [tools, setTools] = useState<BotTool[]>([]), [templates, setTemplates] = useState<BotTemplate[]>([]);
  const [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    Promise.all([getModelCatalog(controller.signal), getBotTemplates(controller.signal)])
      .then(([c, tpl]) => { setCatalog(c); setTools(tpl.tools); setTemplates(tpl.templates); })
      .catch(err => { if (!controller.signal.aborted) setError(message(err, "模板暂时无法读取。")); });
    return () => controller.abort();
  }, [attempt]);
  const retry = useCallback(() => setAttempt(n => n + 1), []);
  return { catalog, tools, templates, error, retry, loaded: catalog !== null };
}
