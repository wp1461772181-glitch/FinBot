import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { StatefulButton } from "@/components/state/StatefulButton";
import { notify } from "@/components/state/notify";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Segmented } from "@/components/Segmented";
import { getUploadedEvidence, uploadEvidence } from "../../../api/evidence-uploads";
import type { UploadedEvidence } from "../../../types";
import { formatDateTime, getLocalePreference, useLocale } from "../../../i18n";
import { actionMessage } from "../support";
import { Dropzone } from "./Dropzone";
import { StarPicker } from "./StarPicker";
import { StarsReadout } from "./Stars";
import { REASON_MAX, TITLE_MAX, firstInvalid, uploadInput, validateUpload } from "./evidence-upload.mjs";
import { httpsUrl, sortUploaded } from "./evidence-model.mjs";

type Impact = "low" | "medium" | "high";
type Phase = "idle" | "loading" | "success" | "error";
const IMPACT_OPTIONS: Array<{ value: Impact; phrase: string }> = [{ value: "low", phrase: "低 · 可能影响有限" }, { value: "medium", phrase: "中 · 值得关注" }, { value: "high", phrase: "高 · 可能显著影响市场预期" }];
const ERROR_PHRASE = {
  file: { missing: "请选择要上传的文件。", type: "请选择 TXT、Markdown 或 PDF 文件。" },
  title: { missing: "请填写标题。" },
  sourceUrl: { missing: "请填写原始 HTTPS 来源。", "not-https": "原始来源必须是 https:// 开头的链接。" },
  publishedAt: { missing: "请选择发布时间。" },
  reason: { missing: "请填写评分理由。" },
} as const;

/**
 * 上传媒体材料 (design 4.7, 5.4): a dialog with the file area, title, https source, publication time, the reader's credibility stars, impact and the reason.
 * The rules are the old form's, one for one (evidence-upload.mjs): a form that breaks one is not sent, and says which field, next to it.  The time is the
 * reader's local time (the zone is written under the field) and goes as UTC, as it always did.  The list of what was saved before stays under the form.
 */
export function UploadDialog({ symbol, supported, onClose, returnFocus }: { symbol: string; supported: boolean; onClose: () => void; /** Where the focus goes when the dialog closes (the entry that opened it). */ returnFocus: () => void }) {
  const { t } = useLocale();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [publishedAt, setPublishedAt] = useState("");
  const [stars, setStars] = useState(3);
  const [impact, setImpact] = useState<Impact>("medium");
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [failure, setFailure] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ kind: "loading" } | { kind: "ready"; items: UploadedEvidence[] } | { kind: "error"; message: string }>({ kind: "loading" });
  const fileInput = useRef<HTMLInputElement | null>(null);
  const fields = useRef<Record<string, HTMLElement | null>>({});
  const running = phase === "loading";
  const zone = useMemo(() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { return ""; } }, []);

  useEffect(() => {
    const controller = new AbortController();
    getUploadedEvidence(symbol, controller.signal)
      .then(data => { if (!controller.signal.aborted) setSaved({ kind: "ready", items: data.items ?? [] }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setSaved({ kind: "error", message: actionMessage(error, "暂时无法读取已上传材料。") }); });
    return () => controller.abort();
  }, [symbol]);

  const errors = validateUpload({ file: file ? { name: file.name, type: file.type } : null, title, sourceUrl, publishedAt, reason });
  // A file of a kind we do not read is said so the moment it is chosen; every other rule speaks once the reader has tried to send.
  const shown = (field: keyof typeof errors) => errors[field] && (attempted || (field === "file" && file !== null)) ? errors[field] : undefined;
  const message = (field: keyof typeof ERROR_PHRASE) => { const code = shown(field); return code ? t((ERROR_PHRASE[field] as Record<string, string>)[code]) : null; };
  const reset = () => { setFile(null); setTitle(""); setSourceUrl(""); setPublishedAt(""); setStars(3); setImpact("medium"); setReason(""); setAttempted(false); if (fileInput.current) fileInput.current.value = ""; };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running || !supported) return;
    setAttempted(true);
    const first = firstInvalid(errors);
    if (first || !file) { (first === "file" || !first ? fileInput.current : fields.current[first])?.focus(); return; }
    setFailure(null);
    setPhase("loading");
    try {
      const item = await uploadEvidence(symbol, uploadInput({ file, title, sourceUrl, publishedAt, stars, impact, reason }));
      setSaved(previous => ({ kind: "ready", items: sortUploaded([item, ...(previous.kind === "ready" ? previous.items : [])]) }));
      reset();
      setPhase("success");
      notify.success(t("材料已保存"), { description: t("它仍需经过 AI 分析并被预测简报引用，才会出现在对应版本的证据卡片中。") });
      window.setTimeout(() => setPhase("idle"), 1600);
    } catch (error: unknown) {
      setFailure(actionMessage(error, "上传材料失败。"));
      setPhase("error");
      window.setTimeout(() => setPhase("idle"), 1600);
    }
  }

  const describe = (field: string) => (shown(field as keyof typeof errors) ? `upload-error-${field}` : undefined);
  const errorLine = (field: keyof typeof ERROR_PHRASE) => { const text = message(field); return text ? <p id={`upload-error-${field}`} role="alert" data-testid={`upload-error-${field}`} className="text-caption text-danger">{text}</p> : null; };
  const label = "flex min-w-0 flex-col gap-1.5 text-small font-medium text-ink";
  return <Dialog open onOpenChange={next => { if (!next && !running) onClose(); }}>
    <DialogContent data-testid="upload-dialog" aria-describedby="upload-dialog-description" closeLabel={t("关闭上传窗口")} onInteractOutside={event => { if (running) event.preventDefault(); }} onCloseAutoFocus={event => { event.preventDefault(); returnFocus(); }}
      className="max-h-[92dvh] gap-4 overflow-y-auto p-4 sm:max-w-xl sm:p-6">
      <DialogHeader>
        <p className="text-caption text-muted-foreground">{symbol} / {t("来源记录")}</p>
        <DialogTitle className="text-title-s">{t("上传媒体材料")}</DialogTitle>
        <DialogDescription id="upload-dialog-description">{t("保存报道文件、原始链接和你的来源可信度判断。")}</DialogDescription>
      </DialogHeader>
      <form noValidate onSubmit={submit} data-testid="upload-form" className="flex min-w-0 flex-col gap-4">
        {!supported && <p className="text-small text-muted-foreground">{t("上传需要有效的美股代码。")}</p>}
        <div className="flex min-w-0 flex-col gap-1.5">
          <span className="text-small font-medium text-ink">{t("材料文件")}</span>
          <Dropzone file={file} onFile={setFile} disabled={!supported || running} invalid={Boolean(shown("file"))} describedBy={describe("file")} inputRef={fileInput} />
          {errorLine("file")}
        </div>
        <label className={label}>{t("标题")}
          <Input ref={element => { fields.current.title = element; }} data-testid="upload-title" value={title} maxLength={TITLE_MAX} disabled={!supported || running} aria-invalid={Boolean(shown("title")) || undefined} aria-describedby={describe("title")} onChange={event => setTitle(event.target.value)} placeholder={t("例如：权威媒体报道产品重大问题")} />
          {errorLine("title")}
        </label>
        <label className={label}>{t("原始 HTTPS 来源")}
          <Input ref={element => { fields.current.sourceUrl = element; }} data-testid="upload-url" type="url" inputMode="url" value={sourceUrl} disabled={!supported || running} aria-invalid={Boolean(shown("sourceUrl")) || undefined} aria-describedby={describe("sourceUrl")} onChange={event => setSourceUrl(event.target.value)} placeholder="https://…" />
          {errorLine("sourceUrl")}
        </label>
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <label className={label}>{t("发布时间")}
            <Input ref={element => { fields.current.publishedAt = element; }} data-testid="upload-published" type="datetime-local" value={publishedAt} disabled={!supported || running} aria-invalid={Boolean(shown("publishedAt")) || undefined} aria-describedby={describe("publishedAt")} onChange={event => setPublishedAt(event.target.value)} className="w-full" />
            <span className="text-caption font-normal text-muted-foreground">{t("按你本机的时区填写")}{zone ? ` · ${zone}` : ""}</span>
            {errorLine("publishedAt")}
          </label>
          <StarPicker value={stars} onChange={setStars} name={`credibility-${symbol}`} disabled={!supported || running} />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Segmented name={`impact-${symbol}`} legend={t("潜在影响程度")} value={impact} disabled={!supported || running} onChange={setImpact} testid="upload-impact"
            options={IMPACT_OPTIONS.map(option => ({ value: option.value, label: t(option.phrase) }))} />
          <p className="text-caption text-muted-foreground">{t("这是对潜在重要性的判断，不是涨跌方向或概率预测。")}</p>
        </div>
        <label className={label}>{t("评分理由")}
          <Textarea ref={element => { fields.current.reason = element; }} data-testid="upload-reason" value={reason} rows={2} maxLength={REASON_MAX} disabled={!supported || running} aria-invalid={Boolean(shown("reason")) || undefined} aria-describedby={describe("reason")} onChange={event => setReason(event.target.value)} placeholder={t("例如：媒体的一手采访、交叉报道情况，或尚待确认的原因")} />
          {errorLine("reason")}
        </label>
        {failure && <ErrorBar message={failure} />}
        <div className="flex justify-end"><StatefulButton type="submit" data-testid="upload-submit" phase={phase} disabled={!supported}>{t("保存媒体材料")}</StatefulButton></div>
      </form>
      <SavedList state={saved} />
    </DialogContent>
  </Dialog>;
}

function SavedList({ state }: { state: { kind: "loading" } | { kind: "ready"; items: UploadedEvidence[] } | { kind: "error"; message: string } }) {
  const { t } = useLocale();
  if (state.kind === "loading") return <DelayedSkeleton><SkeletonRows rows={2} /></DelayedSkeleton>;
  if (state.kind === "error") return <ErrorBar message={state.message} />;
  if (!state.items.length) return <p data-testid="uploaded-empty" className="text-small text-muted-foreground">{t("还没有手动上传的媒体材料。")}</p>;
  const shown = sortUploaded(state.items).slice(0, 4);
  return <section data-testid="uploaded-list" aria-label={t("最近上传的媒体材料")} className="flex min-w-0 flex-col gap-2 border-t border-line pt-4">
    <p className="text-caption text-muted-foreground">{t("最近保存")} {shown.length} / {state.items.length} {t("份")}</p>
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {shown.map(item => { const link = httpsUrl(item.source_url); return <li key={item.id} data-testid="uploaded-item" className="material-fact flex min-w-0 flex-col gap-1 px-3 py-2 text-small">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1"><strong className="min-w-0 font-medium text-ink [overflow-wrap:anywhere]">{item.title}</strong><StarsReadout value={item.credibility_stars} /></div>
        <p className="text-caption text-muted-foreground">{formatTime(item.published_at)} · {t("潜在影响")}{t({ low: "低", medium: "中", high: "高" }[item.impact_severity ?? "medium"])}</p>
        {link && <a href={link} target="_blank" rel="noopener noreferrer" className="w-fit rounded-sm text-caption text-brand outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{t("打开原始来源")}</a>}
      </li>; })}
    </ul>
  </section>;
}

function formatTime(value: string | null | undefined) {
  if (!value) return getLocalePreference() === "en-US" ? "Time not recorded" : "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(date, getLocalePreference(), "UTC");
}

