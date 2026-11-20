import { useRef, useState, type ReactNode } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { notify } from "@/components/state/notify";
import { getKnowledgeCandidates, getKnowledgeChunks, getKnowledgeDocuments, getKnowledgeImportable, importKnowledge, reviewKnowledgeCandidate, retryKnowledgeDocument, runKnowledgeIndex, testKnowledgeRetrieval, withdrawKnowledgeDocument, type KnowledgeDocumentSummary } from "../../../api/knowledge-docs";
import { uploadEvidence } from "../../../api/evidence-uploads";
import { useLocale } from "../../../i18n";
import { Dropzone } from "../../research/evidence/Dropzone";
import { fill } from "../fill";
import { useLoad } from "../../use-load";
import { ChunksDrawer, type ChunkDetail } from "./ChunksDrawer";
import { Candidates, DocsList, type Candidate } from "./DocsList";
import { FIXED_IMPACT, FIXED_STARS, QUERY_MAX, SOURCES, SYMBOL_MAX, localDateTimeInput, parseLocalDateTime, retrievalArgs, retrievalText, uploadReady, type KnowledgeSource } from "./knowledge-form.mjs";

type Importable = { id: string; title: string; symbol: string | null; source_type: string };

function Section({ id, title, description, children }: { id: string; title: ReactNode; description?: string; children: ReactNode }) {
  return <section aria-labelledby={`knowledge-${id}-title`} data-testid={`knowledge-section-${id}`} className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-4">
    <div className="flex flex-col gap-1"><h2 id={`knowledge-${id}-title`} className="text-title-s text-ink">{title}</h2>{description && <p data-testid={`knowledge-section-${id}-note`} className="max-w-3xl text-small text-muted-foreground">{description}</p>}</div>
    {children}
  </section>;
}

/**
 * 研究知识库 (#/assistant/knowledge, design 4.11): the library the agent's knowledge search reads — upload material, import what exists, run the index queue, test a retrieval, read the documents and review the candidates.
 * Every request is the old page's (src/api/knowledge-docs.ts and evidence-uploads.ts, unchanged); the stock code and the source chosen under 导入已有材料 are one state, which the upload form, the import form and the retrieval test all read.
 * Nothing on this page says that an import is searchable at once: the status of a document is the server's word, as it gave it.
 */
export function KnowledgePage() {
  const { t } = useLocale();
  const library = useLoad(async signal => { const [docs, candidates] = await Promise.all([getKnowledgeDocuments(), getKnowledgeCandidates()]); void signal; return { docs, candidates }; });
  const docs = library.data?.docs ?? null, candidates = library.data?.candidates ?? [];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [source, setSource] = useState<KnowledgeSource>("upload");
  const [symbol, setSymbol] = useState("AAPL");
  const [available, setAvailable] = useState<Importable[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  // upload form
  const [file, setFile] = useState<File | null>(null), [title, setTitle] = useState(""), [url, setUrl] = useState(""), [publishedAt, setPublishedAt] = useState(localDateTimeInput()), [reason, setReason] = useState("");
  const [timeError, setTimeError] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  // retrieval
  const [question, setQuestion] = useState(""), [result, setResult] = useState<string | null>(null);
  // chunks drawer
  const [chunks, setChunks] = useState<{ open: boolean; doc: KnowledgeDocumentSummary | null; detail: ChunkDetail | null; error: unknown; loading: boolean }>({ open: false, doc: null, detail: null, error: null, loading: false });
  const opener = useRef<HTMLElement | null>(null);

  /** One action: the page is busy, an error goes to the bar, `done` is said when it worked. */
  async function act<T>(work: () => Promise<T>, done?: (value: T) => string, refresh = false): Promise<T> {
    setBusy(true); setError(null);
    try { const value = await work(); if (refresh) await library.reload(); if (done) notify.success(done(value), { id: "knowledge:done" }); return value; }
    catch (failure) { setError(failure); throw failure; }
    finally { setBusy(false); }
  }
  const loadImportable = async (kind: KnowledgeSource, code: string) => { setAvailable(await getKnowledgeImportable(kind, code)); setSelected([]); };

  async function upload() {
    if (!file) return;
    const when = parseLocalDateTime(publishedAt);
    setTimeError(!when);
    if (!when) throw new Error(t("发布时间无效，请重新选择日期和时间"));
    await act(async () => {
      await uploadEvidence(symbol, { file, title, sourceUrl: url, publishedAt: when.toISOString(), credibilityStars: FIXED_STARS, credibilityReason: reason, impactSeverity: FIXED_IMPACT });
      notify.success(t("上传已保存；请选择材料并导入知识库"), { id: "knowledge:done" });
      setSource("upload");
      await loadImportable("upload", symbol);
    });
  }
  const openChunks = (doc: KnowledgeDocumentSummary, from: HTMLElement) => {
    opener.current = from;
    setChunks({ open: true, doc, detail: null, error: null, loading: true });
    getKnowledgeChunks(doc.id).then(detail => setChunks(current => current.doc?.id === doc.id ? { ...current, detail, loading: false } : current)).catch(failure => setChunks(current => current.doc?.id === doc.id ? { ...current, error: failure, loading: false } : current));
  };
  const review = (candidate: Candidate, approved: boolean) => void act(() => reviewKnowledgeCandidate(candidate.id, approved, "operator"), () => t(approved ? "已审核，已加入索引队列" : "候选已拒绝"), true).catch(() => undefined);
  const symbolBox = (id: string) => <Input id={id} value={symbol} maxLength={SYMBOL_MAX} className="font-mono uppercase max-sm:h-11 sm:w-40" onChange={event => setSymbol(event.target.value.toUpperCase())} />;

  return <main data-testid="knowledge-page" aria-labelledby="knowledge-title" className="mx-auto flex w-full min-w-0 max-w-[1100px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <h1 id="knowledge-title" className="text-title-m text-ink">{t("研究知识库")}</h1>
    {error != null && <ErrorBar error={error} onRetry={() => void library.reload()} retrying={library.loading} />}
    {library.error != null && <ErrorBar error={library.error} onRetry={() => void library.reload()} retrying={library.loading} />}

    <Section id="upload" title={t("上传并导入材料")} description={t("支持 TXT、Markdown 和 PDF；上传内容先归当前会话所有，再导入与索引。")}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field><FieldLabel htmlFor="knowledge-upload-symbol">{t("股票代码")}</FieldLabel>{symbolBox("knowledge-upload-symbol")}</Field>
        <Field><FieldLabel htmlFor="knowledge-upload-title">{t("材料标题")}</FieldLabel><Input id="knowledge-upload-title" data-testid="knowledge-upload-title" value={title} className="max-sm:h-11" onChange={event => setTitle(event.target.value)} /></Field>
        <Field><FieldLabel htmlFor="knowledge-upload-url">{t("来源链接")}</FieldLabel><Input id="knowledge-upload-url" data-testid="knowledge-upload-url" value={url} className="max-sm:h-11" onChange={event => setUrl(event.target.value)} /></Field>
        <Field data-invalid={timeError || undefined}>
          <FieldLabel htmlFor="knowledge-upload-time">{t("发布时间")}</FieldLabel>
          <Input id="knowledge-upload-time" data-testid="knowledge-upload-time" type="datetime-local" value={publishedAt} aria-invalid={timeError || undefined} className="max-sm:h-11" onChange={event => { setPublishedAt(event.target.value); setTimeError(false); }} />
          {timeError && <FieldError>{t("发布时间无效，请重新选择日期和时间")}</FieldError>}
        </Field>
        <Field className="sm:col-span-2"><FieldLabel htmlFor="knowledge-upload-reason">{t("来源说明")}</FieldLabel><Input id="knowledge-upload-reason" data-testid="knowledge-upload-reason" value={reason} className="max-sm:h-11" onChange={event => setReason(event.target.value)} /></Field>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5"><span className="text-small font-medium text-ink">{t("材料文件")}</span><Dropzone file={file} onFile={setFile} disabled={busy} inputRef={fileInput} /></div>
      <div className="flex justify-end"><StatefulButton type="button" data-testid="knowledge-upload-submit" disabled={busy || !uploadReady({ file, title, url, reason })} className="max-sm:h-11" onClick={upload}>{t("上传材料")}</StatefulButton></div>
    </Section>

    <Section id="import" title={t("导入已有材料")} description={t("可导入当前会话拥有的上传、已获取的 SEC 摘录、FAQ，或已保存 AI 分析。未知 owner 的旧上传及分析不会公开。")}>
      <div className="flex flex-wrap items-end gap-3">
        <Field className="w-full sm:w-64"><FieldLabel htmlFor="knowledge-source">{t("来源")}</FieldLabel>
          <Select value={source} onValueChange={value => setSource(value as KnowledgeSource)}>
            <SelectTrigger id="knowledge-source" data-testid="knowledge-source" className="w-full max-sm:h-11"><SelectValue /></SelectTrigger>
            <SelectContent>{SOURCES.map(option => <SelectItem key={option.value} value={option.value}>{t(option.label)}</SelectItem>)}</SelectContent>
          </Select></Field>
        <Field className="w-auto"><FieldLabel htmlFor="knowledge-import-symbol">{t("股票代码")}</FieldLabel>{symbolBox("knowledge-import-symbol")}</Field>
        <Button type="button" variant="outline" data-testid="knowledge-load" disabled={busy} className="max-sm:h-11" onClick={() => void act(() => loadImportable(source, symbol)).catch(() => undefined)}>{t("载入可选材料")}</Button>
      </div>
      {available.length > 0 && <>
        <ul data-testid="knowledge-importable" className="m-0 flex list-none flex-col gap-1 p-0">{available.map(item => <li key={item.id}>
          <Field orientation="horizontal" className="min-h-9 items-center gap-2.5 rounded-sm px-1 max-sm:min-h-11">
            <Checkbox id={`importable-${item.id}`} data-testid="knowledge-importable-item" checked={selected.includes(item.id)} onCheckedChange={on => setSelected(current => on === true ? [...current, item.id] : current.filter(x => x !== item.id))} />
            <FieldLabel htmlFor={`importable-${item.id}`} className="flex-wrap gap-x-2 font-normal"><span className="text-ink">{item.title}</span><span className="font-mono text-caption text-muted-foreground">{item.symbol || item.source_type}</span></FieldLabel>
          </Field>
        </li>)}</ul>
        <div className="flex justify-end"><StatefulButton type="button" data-testid="knowledge-import" disabled={busy || !selected.length} className="max-sm:h-11"
          onClick={() => act(() => importKnowledge(source, selected), r => fill(t("接收 {accepted} 份材料，生成 {chunks} 个块"), { accepted: r.accepted_sources, chunks: r.chunks }), true)}>{fill(t("导入所选 {n} 份"), { n: selected.length })}</StatefulButton></div>
      </>}
    </Section>

    <Section id="index" title={t("索引队列")} description={t("本地运行需要 RAG_ENABLED=true；每次最多处理 100 个 pending 任务。")}>
      <div><StatefulButton type="button" data-testid="knowledge-index" disabled={busy} className="max-sm:h-11" onClick={() => act(() => runKnowledgeIndex(), r => fill(t("索引完成 {indexed}，失败 {failed}"), { indexed: r.indexed, failed: r.failed }), true)}>{t("运行索引")}</StatefulButton></div>
    </Section>

    <Section id="retrieval" title={t("检索测试")} description={t("直接走当前 BGE/Milvus 检索路径，并应用当前会话的 owner scope。")}>
      <dl data-testid="knowledge-retrieval-inputs" className="m-0 flex flex-wrap items-center gap-x-5 gap-y-1 text-small">
        <div className="flex items-center gap-1.5"><dt className="text-muted-foreground">{t("来源")}</dt><dd data-testid="knowledge-retrieval-source" className="m-0 text-ink">{t(SOURCES.find(option => option.value === source)?.label ?? source)}</dd></div>
        <div className="flex items-center gap-1.5"><dt className="text-muted-foreground">{t("股票代码")}</dt><dd data-testid="knowledge-retrieval-symbol" className="m-0 font-mono text-ink">{source === "faq" ? t("不带代码") : symbol || "—"}</dd></div>
      </dl>
      <p className="text-caption text-muted-foreground">{t("这两项取自上面「导入已有材料」里的来源和股票代码。")}</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <Field className="min-w-0 flex-1"><FieldLabel htmlFor="knowledge-query">{t("查询")}</FieldLabel><Input id="knowledge-query" data-testid="knowledge-query" value={question} maxLength={QUERY_MAX} className="max-sm:h-11" onChange={event => setQuestion(event.target.value)} /></Field>
        <StatefulButton type="button" data-testid="knowledge-test" disabled={busy || !question.trim()} className="max-sm:h-11"
          onClick={() => act(async () => { const [kind, keyword, code] = retrievalArgs(source, question, symbol); const answer = await testKnowledgeRetrieval(kind, keyword, code); setResult(retrievalText(answer)); }, () => t("已通过当前权限执行真实知识检索"))}>{t("测试检索")}</StatefulButton>
      </div>
      {result && <pre data-testid="knowledge-result" className="material-fact m-0 max-h-96 overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-small text-ink">{result}</pre>}
    </Section>

    <Section id="docs" title={<>{t("文档")} · <span className="font-mono">{docs?.length ?? 0}</span></>}>
      {!docs && library.loading && <DelayedSkeleton><div role="status" aria-busy="true" className="flex flex-col gap-2"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2].map(i => <Skeleton key={i} className="h-14 w-full" />)}</div></DelayedSkeleton>}
      {docs && <DocsList docs={docs} busy={busy} onOpen={openChunks}
        onRetry={doc => void act(() => retryKnowledgeDocument(doc.id), () => t("已重新排入索引队列"), true).catch(() => undefined)} onWithdraw={doc => void act(() => withdrawKnowledgeDocument(doc.id), () => t("文档已软撤回"), true).catch(() => undefined)} />}
    </Section>

    <Section id="candidates" title={<>{t("待审核候选")} · <span className="font-mono">{candidates.length}</span></>}>
      <Candidates candidates={candidates} busy={busy} onReview={review} />
    </Section>

    <ChunksDrawer open={chunks.open} onOpenChange={open => setChunks(current => ({ ...current, open }))} title={chunks.doc?.title ?? ""} detail={chunks.detail} error={chunks.error} loading={chunks.loading}
      returnFocus={() => { (opener.current?.isConnected ? opener.current : null)?.focus(); }} />
  </main>;
}
