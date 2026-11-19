import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatefulButton } from "@/components/state/StatefulButton";
import { notify } from "@/components/state/notify";
import { ApiError } from "../../../api/base";
import { getMaterialLibrary } from "../../../api/material-library";
import type { FilingScanResult, MaterialItem } from "../../../types";
import { translatePhrase, useLocale } from "../../../i18n";
import { librarySymbol, usableFocus, type UsableFocus } from "../../../material-focus.mjs";
import "../../../styles/forecast.css";
import { MaterialDetail } from "./MaterialDetail";
import { usePhone } from "./use-phone";
import { MaterialFilters } from "./MaterialFilters";
import { MaterialList, type PageState } from "./MaterialList";
import { DEFAULT_FILTERS, PAGE_SIZE, withoutFilter, type FilterKey, type Filters } from "./materials-model.mjs";

// The bar is a chunk of its own, fetched when a task runs (the shell's dock does the same).
const TaskBar = lazy(() => import("@/components/state/TaskBar").then(m => ({ default: m.TaskBar })));

/**
 * 材料库 (design 4.7): a list on the left with its filter bar above, the chosen material on the right (a full-screen drawer on a phone).  A focus comes from the
 * address (?focus=&type=, with &analysis= from a brief's citation): the library finds that material in the stock's list, opens its page and chooses it.
 * `embedded` is the company page's 材料 tab: the same library on one company, without its own page frame.
 */
export function MaterialLibrary({ symbol, focus, onScan, embedded = false }: { symbol: string; focus: unknown; onScan: () => Promise<FilingScanResult>; embedded?: boolean }) {
  const { t } = useLocale();
  const phone = usePhone();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const listSymbol = librarySymbol(filters.scope, symbol);
  const [offset, setOffset] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [materialFocus, setMaterialFocus] = useState<UsableFocus | null>(() => usableFocus(focus, symbol));
  const [focusAnalysisId, setFocusAnalysisId] = useState<string | null>(null);
  const [focusMessage, setFocusMessage] = useState<string | null>(null);
  const [page, setPage] = useState<PageState>({ kind: "loading" });
  const [selected, setSelected] = useState<MaterialItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [scrollTo, setScrollTo] = useState<string | null>(null);
  const selectedRef = useRef<MaterialItem | null>(null);
  const pageRequestRef = useRef(0);
  selectedRef.current = selected;

  const wanted = JSON.stringify([listSymbol, filters.sourceType, filters.analysisStatus, filters.order, offset, refreshKey]);
  useEffect(() => {
    const controller = new AbortController();
    const requestNumber = ++pageRequestRef.current;
    setPage({ kind: "loading" });
    getMaterialLibrary(listSymbol, { sourceType: filters.sourceType, analysisStatus: filters.analysisStatus, order: filters.order, offset, signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted || requestNumber !== pageRequestRef.current) return;
        setPage({ kind: "ready", items: result.items, total: result.total, key: wanted });
        const previous = selectedRef.current;
        setSelected(previous?.symbol === symbol
          ? result.items.find(item => item.source_id === previous.source_id && item.source_type === previous.source_type) ?? result.items[0] ?? null
          : result.items[0] ?? null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestNumber !== pageRequestRef.current) return;
        setPage({ kind: "error", message: translatePhrase(error instanceof ApiError ? error.message : "暂时无法读取材料目录，请确认本地 API 和材料分析迁移状态。") });
      });
    return () => controller.abort();
  }, [listSymbol, symbol, filters.sourceType, filters.analysisStatus, filters.order, offset, refreshKey]);

  // The material an address named: the stock's list is read page by page (newest stored first) until it is found.
  useEffect(() => {
    if (!materialFocus) return;
    const controller = new AbortController();
    const requestNumber = ++pageRequestRef.current;
    setFocusMessage(null);
    async function locateFocusedMaterial() {
      try {
        let total = 0;
        for (let pageOffset = 0; pageOffset === 0 || pageOffset < total; pageOffset += PAGE_SIZE) {
          const result = await getMaterialLibrary(symbol, { sourceType: materialFocus!.source_type, order: "recent", offset: pageOffset, signal: controller.signal });
          total = result.total;
          const match = result.items.find(item => item.source_type === materialFocus!.source_type && item.source_id === materialFocus!.source_id);
          if (controller.signal.aborted || requestNumber !== pageRequestRef.current) return;
          if (match) {
            setPage({ kind: "ready", items: result.items, total });
            setOffset(pageOffset);
            setSelected(match);
            setScrollTo(`${match.source_type}:${match.source_id}`);
            setDetailOpen(true);
            // The list is the one the material was found in (this stock, newest stored first, its kind): the page offset is that list's, so the row is on the page shown.
            setFilters(current => ({ ...current, scope: "current", order: "recent", sourceType: materialFocus!.source_type }));
            setFocusAnalysisId(materialFocus!.analysis_id);
            setMaterialFocus(null);
            return;
          }
          if (pageOffset + PAGE_SIZE >= total) break;
        }
        if (!controller.signal.aborted && requestNumber === pageRequestRef.current) {
          // A brief citation can fall back to its forecast version; a plain link has nowhere else to go.
          setFocusMessage(translatePhrase(materialFocus!.analysis_id
            ? "简报引用的材料当前不在目录中，仍可从预测版本返回查看。"
            : "这份材料当前不在该股票的目录中（可能已删除）。可切到「全部股票」查找，或点「扫描 SEC 资料」重新入库。"));
          setMaterialFocus(null);
          setRefreshKey(current => current + 1); // the list that was dropped while the lookup ran is read again
        }
      } catch (error) {
        if (!controller.signal.aborted && requestNumber === pageRequestRef.current) {
          setFocusMessage(translatePhrase(error instanceof ApiError ? error.message : "无法定位简报引用的材料。"));
          setMaterialFocus(null);
          setRefreshKey(current => current + 1);
        }
      }
    }
    void locateFocusedMaterial();
    return () => controller.abort();
  }, [materialFocus, symbol]);

  const refresh = useCallback(() => { setRefreshKey(current => current + 1); }, []);
  const change = (key: FilterKey, value: string) => {
    if (key !== "order") { setMaterialFocus(null); setFocusAnalysisId(null); }
    setFilters(current => ({ ...current, [key]: value } as Filters));
    setOffset(0);
  };
  const clear = (key: FilterKey) => { setMaterialFocus(null); setFocusAnalysisId(null); setFilters(current => withoutFilter(current, key)); setOffset(0); };
  const clearAll = () => { setMaterialFocus(null); setFocusAnalysisId(null); setFilters(current => ({ ...DEFAULT_FILTERS, order: current.order })); setOffset(0); };
  const choose = (item: MaterialItem) => { setFocusAnalysisId(null); setScrollTo(null); setSelected(item); setDetailOpen(true); };

  const scan = useCallback(async () => {
    const result = await onScan();
    refresh();
    notify.success(`${t("扫描完成")}：${t("发现")} ${result.discovered_count} ${t("份")}，${t("新增")} ${result.created_count} ${t("份")}。`);
  }, [onScan, refresh, t]);
  const scanFailed = (error: unknown) => notify.error(translatePhrase(error instanceof ApiError ? error.message : error instanceof Error ? error.message : "扫描 SEC 资料失败。"));

  // On a phone the detail is the whole screen over the list.  It is the same element in both layouts (only its style changes), so a window that is resized across the
  // breakpoint, or a picture taken of the whole page, never unmounts it and drops what the reader had open (tab, version, a job).
  const overlay = phone && detailOpen && selected !== null;
  const back = useRef<HTMLButtonElement | null>(null);
  const layer = useRef<HTMLDivElement | null>(null);
  const wasOverlay = useRef(false);
  useEffect(() => {
    if (!overlay) {
      if (wasOverlay.current) document.querySelector<HTMLElement>("[data-testid=material-row][data-selected]")?.focus();
      wasOverlay.current = false;
      return;
    }
    wasOverlay.current = true;
    // Everything outside the layer cannot be reached while it is open (the shell's sidebar button, top bar and tab bar, the company page's own header and tabs, the
    // library's list): on every level of the layer's ancestor chain the siblings of that level are made inert; the ancestors themselves must not be (that would shut the layer too).
    const shut: Element[] = [];
    for (let level: HTMLElement | null = layer.current; level && level !== document.body; level = level.parentElement) {
      for (const sibling of Array.from(level.parentElement?.children ?? [])) {
        if (sibling !== level && !sibling.hasAttribute("inert")) { sibling.setAttribute("inert", ""); shut.push(sibling); }
      }
    }
    back.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // With the rest of the page shut, Tab past the last control would leave the document (to the browser's own bar): it wraps inside the layer instead.  A focus in a
    // popup of the layer (a Select's list is drawn outside it) is left alone.
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) { setDetailOpen(false); return; }
      const root = layer.current;
      if (event.key !== "Tab" || event.defaultPrevented || !root) return;
      const active = document.activeElement;
      if (active && active !== document.body && !root.contains(active)) return;
      const stops = Array.from(root.querySelectorAll<HTMLElement>("a[href],button,input,select,textarea,summary,[tabindex]:not([tabindex='-1'])"))
        .filter(node => !(node as HTMLButtonElement).disabled && node.getClientRects().length > 0 && !node.closest("[inert]"));
      const first = stops[0], last = stops[stops.length - 1];
      if (!first || !last) { event.preventDefault(); return; }
      const leaving = active === document.body || !root.contains(active) || (event.shiftKey ? active === first || active === root : active === last);
      if (leaving) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => { shut.forEach(node => node.removeAttribute("inert")); document.body.style.overflow = previousOverflow; window.removeEventListener("keydown", onKeyDown); };
  }, [overlay]);

  const Heading = embedded ? "h2" : "h1";
  const Root = embedded ? "section" : "main";
  const detail = selected
    ? <MaterialDetail key={`${symbol}:${selected.source_type}:${selected.source_id}`} material={selected} initialAnalysisId={focusAnalysisId} onUpdated={refresh} />
    : <div data-testid="material-detail-empty" className="flex min-h-48 items-center justify-center rounded-md border border-dashed border-line px-4 text-center text-small text-muted-foreground">{t("选择一份材料查看分析与原文。")}</div>;
  return <Root data-testid="material-library" aria-labelledby="material-library-title" className={embedded ? "flex min-w-0 flex-col gap-4" : "mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6"}>
    <header className="flex flex-wrap items-end gap-x-4 gap-y-2">
      {/* On the company page the tab already says 材料: the title stays for screen readers and the one-line note remains. */}
      <div className={embedded ? "sr-only" : "min-w-0"}><p className="text-caption text-muted-foreground mb-[1em]">{symbol} / {t("研究材料")}</p><Heading id="material-library-title" className="text-title-m text-ink mb-[0.67em]">{t("材料库")}</Heading></div>
      <p className="hidden text-caption text-muted-foreground sm:block mb-[1em]">{t("每页 10 条 · 分析版本与原文分开保存")}</p>
      <StatefulButton type="button" variant="outline" data-testid="material-scan" className="ml-auto max-sm:h-11" onClick={scan} onError={scanFailed}>{t("扫描 SEC 资料")}</StatefulButton>
    </header>
    <div data-task-strip="" data-testid="material-jobs" className="empty:hidden"><Suspense fallback={null}><TaskBar /></Suspense></div>
    {focusMessage && <p role="status" data-testid="focus-message" className="rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2 mb-[1em]">{focusMessage}</p>}
    <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <section aria-label={t("材料列表")} data-testid="material-list-section" data-wanted={wanted} data-loaded={page.kind === "ready" ? page.key ?? "" : ""} className="flex min-w-0 flex-col gap-3">
        <MaterialFilters symbol={symbol} filters={filters} total={page.kind === "ready" ? page.total : null} onChange={change} onClear={clear} />
        <MaterialList symbol={symbol} page={page} filters={filters} offset={offset} selected={selected} scrollTo={scrollTo} showSymbol={filters.scope === "all"} onSelect={choose} onOffset={setOffset} onRetry={refresh} onClear={clearAll} />
      </section>
      <div ref={layer} data-testid={overlay ? "material-drawer" : "material-detail-pane"} {...(overlay ? { role: "dialog", "aria-modal": true, "aria-label": selected?.title } : {})}
      className={overlay ? "fixed inset-0 z-50 flex flex-col bg-background outline-none" : phone ? "hidden" : "min-w-0"}>
        {overlay && <div className="flex shrink-0 items-center gap-2 border-b border-line p-2">
          <Button ref={back} type="button" variant="ghost" size="sm" onClick={() => setDetailOpen(false)} className="min-h-11" data-testid="material-drawer-back"><ArrowLeft aria-hidden="true" />{t("返回列表")}</Button>
        </div>}
        <div className={overlay ? "min-h-0 flex-1 overflow-y-auto p-4" : undefined}>{detail}</div>
      </div>
    </div>
  </Root>;
}

