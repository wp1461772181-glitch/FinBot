import { useId, useRef, useState, type DragEvent } from "react";
import { FileText, UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale } from "../../../i18n";
import { FILE_ACCEPT } from "./evidence-upload.mjs";

const sizeText = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

/**
 * The file area of the upload form: a box to drop a file on or press to choose one (a native file input behind it, so the keyboard and the screen
 * reader get the platform's own control).  It keeps one file; the kind is checked by the form (which says so next to the box), not here, so a
 * wrong file is shown and named rather than silently ignored.  `invalid` is the form's verdict on it.
 */
export function Dropzone({ file, onFile, disabled, invalid, describedBy, inputRef }: { file: File | null; onFile: (file: File | null) => void; disabled?: boolean; invalid?: boolean; describedBy?: string; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const { t } = useLocale();
  const id = useId();
  const [over, setOver] = useState(false);
  const counter = useRef(0);
  const drop = (event: DragEvent) => { event.preventDefault(); counter.current = 0; setOver(false); if (!disabled) onFile(event.dataTransfer.files?.[0] ?? null); };
  return <div data-slot="dropzone" data-over={over ? "" : undefined} data-invalid={invalid ? "" : undefined}
    onDragEnter={event => { event.preventDefault(); counter.current += 1; setOver(true); }} onDragLeave={() => { counter.current -= 1; if (counter.current <= 0) { counter.current = 0; setOver(false); } }} onDragOver={event => event.preventDefault()} onDrop={drop}
    className={cn("relative flex min-h-24 flex-col items-center justify-center gap-1.5 rounded-md border border-dashed bg-sunken px-4 py-4 text-center text-small text-ink-2 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring", over ? "border-brand bg-brand-soft" : invalid ? "border-danger" : "border-line-strong", disabled && "opacity-55")}>
    <input ref={inputRef} id={id} data-testid="upload-file" type="file" accept={FILE_ACCEPT} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={describedBy} aria-label={t("材料文件")}
      onChange={event => onFile(event.target.files?.[0] ?? null)} className="absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed" />
    {file
      ? <div className="pointer-events-none flex min-w-0 max-w-full items-center gap-2"><FileText aria-hidden="true" className="size-5 shrink-0 text-muted-foreground" /><span data-testid="upload-file-name" className="min-w-0 truncate font-medium text-ink">{file.name}</span><span className="shrink-0 font-mono text-caption text-muted-foreground">{sizeText(file.size)}</span></div>
      : <><UploadCloud aria-hidden="true" className="pointer-events-none size-6 text-muted-foreground" /><p className="pointer-events-none text-ink">{t("把文件拖到这里，或点击选择")}</p></>}
    <p className="pointer-events-none text-caption text-muted-foreground">{t("支持 TXT、Markdown、PDF")}</p>
    {file && !disabled && <button type="button" aria-label={t("移除已选文件")} onClick={() => { onFile(null); if (inputRef.current) inputRef.current.value = ""; }} className="absolute top-1.5 right-1.5 z-10 inline-flex size-8 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-sm:size-11"><X aria-hidden="true" className="size-4" /></button>}
  </div>;
}
