import { useEffect, useState } from "react";
import { useLocale } from "./i18n";
import { getV2Job } from "./api/forecast-v2";
import type { V2ForecastJob, V2VersionDetail } from "./types";
import { NOT_RECORDED, recordedModel } from "./forecast-model.mjs";
import { EvidenceDetail } from "./ForecastTimeline";
import { asRecord, asText } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";

type AuditRow = { label: string; value: string };

/** What the audit rows read from one saved version: raw values, shown as stored, 未记录 when the version has none. */
function auditRows(version: V2VersionDetail): AuditRow[] {
  const manifest = asRecord(version.model_manifest);
  const decision = asRecord(manifest.decision_provider);
  const { provider, actual_model, requested_model } = recordedModel(version);
  const rows: AuditRow[] = [
    { label: "服务方", value: provider ?? NOT_RECORDED },
    { label: "请求模型", value: requested_model ?? NOT_RECORDED },
    { label: "实际返回模型", value: actual_model ?? NOT_RECORDED },
    { label: "问题版本", value: asText(decision.question_version) ?? NOT_RECORDED },
    { label: "请求编号", value: asText(decision.request_id) ?? NOT_RECORDED },
    { label: "输入哈希", value: asText(decision.input_sha256) ?? NOT_RECORDED },
    { label: "任务编号", value: version.job_id },
  ];
  // A retired control run stays a record like any other; its manifest keys are shown raw, not dressed up.
  if (manifest.hidden_control !== undefined || manifest.control_of_root_id !== undefined) {
    rows.push({ label: "对照记录", value: JSON.stringify({ hidden_control: manifest.hidden_control ?? null, control_of_root_id: manifest.control_of_root_id ?? null }) });
  }
  return rows;
}

/** 审计与来源: collapsed until asked for.  The job is read only once it is opened. */
export function ForecastAudit({ detail }: { detail: ResourceState<{ current: V2VersionDetail; parent: V2VersionDetail | null }> | null }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [job, setJob] = useState<ResourceState<V2ForecastJob> | null>(null);
  const current = detail?.kind === "ready" ? detail.data.current : null;
  const jobId = current?.job_id ?? null;
  useEffect(() => {
    if (!open || !jobId) { setJob(null); return; }
    const controller = new AbortController();
    setJob({ kind: "loading" });
    getV2Job(jobId, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setJob({ kind: "ready", data: next }); })
      .catch(() => { if (!controller.signal.aborted) setJob({ kind: "error", message: "" }); });
    return () => controller.abort();
  }, [open, jobId]);
  return <details className="v2-audit" open={open} onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary>{t("审计与来源")}</summary>
    {open && current && <>
      <dl className="v2-audit-rows">
        {auditRows(current).map((row) => <div key={row.label}><dt>{t(row.label)}</dt><dd><code>{row.value}</code></dd></div>)}
        <div><dt>{t("任务状态")}</dt><dd><code>{job?.kind === "ready" ? `${job.data.status}${job.data.error?.type ? ` · ${job.data.error.type}` : ""} · ${job.data.current_stage}` : job?.kind === "error" ? NOT_RECORDED : "…"}</code></dd></div>
      </dl>
      <EvidenceDetail detail={detail} />
      <details className="v2-audit-raw">
        <summary>{t("模型清单（原始）")}</summary>
        <pre>{JSON.stringify(current.model_manifest, null, 2)}</pre>
      </details>
    </>}
    {open && !current && detail?.kind === "error" && <p className="v2-notice error" role="alert">{detail.message}</p>}
  </details>;
}
