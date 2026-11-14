import { useState } from "react";
import { Check, ChevronRight, Circle, LoaderCircle, X } from "lucide-react";
import type { AgentChatMessage } from "../../api";
import { useLocale } from "../../i18n";
import { legacyToolChips } from "../../process-steps.mjs";
import { describeOutput, flowRows, formatSeconds, nodeTitle, normalizeTrace, stepCount, type FlowNode } from "../../turn-flow.mjs";
import { JsonViewer } from "./JsonViewer";

function StatusMark({ status }: { status: FlowNode["status"] }) {
  if (status === "running") return <LoaderCircle aria-hidden="true" className="size-3.5 text-bot motion-safe:animate-spin" />;
  if (status === "failed") return <X aria-hidden="true" className="size-3.5 text-danger" />;
  if (status === "warn" || status === "cancelled") return <Circle aria-hidden="true" className="size-3 text-muted-foreground" />;
  return <Check aria-hidden="true" className="size-3.5 text-muted-foreground" />;
}

/** One step: its name and time, what it says (the lines turn-flow.mjs gives it) and, folded, the raw data it carried. */
function Step({ node, depth }: { node: FlowNode; depth: 0 | 1 }) {
  const { t } = useLocale();
  const [raw, setRaw] = useState(false);
  const title = nodeTitle(node), lines = describeOutput(node);
  const duration = node.status === "running" ? "…" : typeof node.ms === "number" ? `${formatSeconds(node.ms)} ${t("秒")}` : "";
  return <li data-testid="timeline-step" data-kind={node.kind} data-status={node.status} className={`relative flex flex-col gap-1.5 pb-4 pl-6 ${depth === 1 ? "ml-5" : ""}`}>
    <span aria-hidden="true" className="absolute left-0 top-0.5 flex size-4 items-center justify-center rounded-full bg-background"><StatusMark status={node.status} /></span>
    <span aria-hidden="true" className="absolute bottom-0 left-2 top-5 w-px bg-line" />
    <div className="flex items-baseline gap-2">
      <span className="min-w-0 flex-1 text-body font-medium text-ink">{t(title.label)}{title.suffix}</span>
      {duration && <span className="shrink-0 font-mono text-caption text-muted-foreground">{duration}</span>}
    </div>
    {lines.length > 0 && <dl className="flex flex-col gap-0.5 text-small">
      {lines.map((line, index) => <div key={index} className="flex gap-2"><dt className="shrink-0 text-muted-foreground">{t(line.label)}</dt><dd className="min-w-0 break-words text-ink-2 [overflow-wrap:anywhere]">{line.translate ? t(line.value) : line.value}</dd></div>)}
    </dl>}
    {node.output && <div className="flex flex-col gap-1.5">
      <button type="button" data-testid="raw-toggle" aria-expanded={raw} className="inline-flex w-fit items-center gap-0.5 rounded-sm text-caption text-muted-foreground outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setRaw((x) => !x)}>
        <ChevronRight aria-hidden="true" className={`size-3.5 transition-transform duration-1 ${raw ? "rotate-90" : ""}`} />{t("原始数据")}
      </button>
      {raw && <div className="rounded-sm bg-sunken p-2"><JsonViewer value={node.output} /></div>}
    </div>}
  </li>;
}

/**
 * The 过程 tab: the full timeline of the round (识别意图 → 模型决策 → 工具调用 → 证据核验 → 输出), each step with its time and the
 * result turn-flow.mjs reads from it; the raw data of a step is folded away.  It grows while the turn runs.  An answer from before the
 * step graph has no steps: its time and its old tool badges are all there is.
 */
export default function ProcessTab({ m, running }: { m: AgentChatMessage; i: number; running: boolean }) {
  const { t } = useLocale();
  const nodes = normalizeTrace(m.trace);
  if (nodes.length === 0) {
    const tools = legacyToolChips(m.tool_trace);
    return <div data-testid="process-empty" className="flex flex-col gap-3 px-1 py-2 text-small text-muted-foreground">
      <p>{running ? t("思考中") : t("这一轮没有步骤记录。")}</p>
      {typeof m.thinking_ms === "number" && <p>{t("已思考")} {formatSeconds(m.thinking_ms)} {t("秒")}</p>}
      {tools.length > 0 && <ul className="flex flex-col gap-1">{tools.map((tool) => <li key={tool.id}>{t(tool.label)} · {t(tool.status)}{tool.summary ? ` · ${tool.summary}` : ""}</li>)}</ul>}
    </div>;
  }
  const seconds = typeof m.thinking_ms === "number" ? `${formatSeconds(m.thinking_ms)} ${t("秒")}` : "";
  return <div className="flex flex-col gap-3">
    <h2 className="text-caption font-medium text-muted-foreground">{running ? t("思考中") : seconds ? `${t("已思考")} ${seconds}` : ""}{stepCount(nodes) > 0 ? ` · ${stepCount(nodes)} ${t("步")}` : ""}{m.status === "partially_succeeded" ? ` · ${t("部分来源可用")}` : ""}</h2>
    <ol data-testid="timeline" aria-live={running ? "polite" : undefined} className="flex flex-col">{flowRows(nodes).map((row) => <Step key={row.node.id} node={row.node} depth={row.depth} />)}</ol>
  </div>;
}
