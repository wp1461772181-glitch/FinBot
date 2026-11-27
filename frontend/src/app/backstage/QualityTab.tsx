import { useRef, useState } from "react";
import { readQuality } from "../../api/backstage";
import { badAnswerRow, qualityWeekRow, rulerRunRow, type BadAnswerRow, type QualityWeekRow, type RulerRunRow } from "../../backstage-view.mjs";
import { useLocale } from "../../i18n";
import { useLoad } from "../use-load";
import { AnswerDrawer } from "./AnswerDrawer";
import { BackstageTable, TabState, type Column } from "./BackstageTable";
import { useWords } from "./words";

/**
 * 质量: how his 「好／不好」 runs week by week, the answers he marked 不好 with his reason (a line opens the answer's course, as in 回答), and every ruler run on
 * the box with its pass rate, times and the cases that failed.  The weekly self-check joins it later.  Nothing here writes.
 */
export function QualityTab() {
  const { t } = useLocale();
  const w = useWords();
  const load = useLoad(signal => readQuality(signal), "quality");
  const [openId, setOpenId] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const open = (id: string) => { opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setOpenId(id); };
  const data = load.data;
  const weeks = (data?.feedback ?? []).map(item => qualityWeekRow(item, w));
  const bad = (data?.bad ?? []).map(item => badAnswerRow(item, undefined, w));
  const runs = (data?.ruler ?? []).map(item => rulerRunRow(item, undefined, w));
  const errors = data?.ruler_errors ?? [];

  const weekColumns: Column<QualityWeekRow>[] = [
    { key: "week", header: t("周"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.week}</span> },
    { key: "good", header: t("好"), cell: row => <span className="font-mono tabular-nums">{row.good}</span> },
    { key: "bad", header: t("不好"), cell: row => <span className="font-mono tabular-nums">{row.bad}</span> },
  ];
  const badColumns: Column<BadAnswerRow>[] = [
    { key: "time", header: t("时间（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span> },
    { key: "bot", header: "bot", cell: row => row.bot },
    { key: "question", header: t("问题"), className: "sm:w-[34%]", wide: true, cell: row =>
      <button type="button" data-testid="quality-open" onClick={event => { event.stopPropagation(); open(row.id); }} className="line-clamp-2 text-left text-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{row.question}</button> },
    { key: "reason", header: t("原因"), className: "sm:w-[30%]", wide: true, cell: row => <span className="flex min-w-0 flex-col gap-0.5">
      <span className="[overflow-wrap:anywhere] text-ink-2">{row.reason}</span>
      {row.said && <span className="text-caption text-muted-foreground">{row.said}</span>}
    </span> },
  ];
  const runColumns: Column<RulerRunRow>[] = [
    { key: "time", header: t("时间（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span> },
    { key: "name", header: t("名称"), className: "sm:w-[24%]", wide: true, cell: row => <span className="flex min-w-0 flex-col gap-0.5">
      <span className="font-mono text-ink [overflow-wrap:anywhere]">{row.name}</span>
      {row.note && <span className="text-caption text-muted-foreground">{row.note}</span>}
    </span> },
    { key: "turns", header: t("题数"), cell: row => <span className="font-mono tabular-nums">{row.turns}</span> },
    { key: "pass_rate", header: t("通过率"), cell: row => <span className="font-mono tabular-nums">{row.pass_rate}</span> },
    { key: "p50", header: t("中位数"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.p50}</span> },
    { key: "p90", header: "P90", cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.p90}</span> },
    { key: "failed", header: t("没过的题"), className: "sm:w-[20%]", wide: true, cell: row =>
      <span className={`font-mono [overflow-wrap:anywhere] ${row.all_passed ? "text-muted-foreground" : "text-ink"}`}>{row.failed}</span> },
  ];

  return <div data-testid="quality-tab" className="flex min-w-0 flex-col gap-6">
    <TabState loading={load.loading && !data} error={load.error} empty={false} onRetry={() => void load.reload()} emptyTitle="" emptyDescription="" />
    {data && <>
      <section aria-labelledby="quality-feedback" className="flex min-w-0 flex-col gap-2">
        <h2 id="quality-feedback" className="text-body font-medium text-ink">{t("你的评价")}</h2>
        <p className="text-small text-muted-foreground">{t("最近 8 周，按回答所在的那一周（周一开始，北京时间）统计你点的「好」和「不好」，在对话里说的也算。")}</p>
        <BackstageTable testId="quality-weeks" label={t("每周评价")} columns={weekColumns} rows={weeks} rowKey={row => row.id} />
        <h3 className="text-small font-medium text-ink">{t("被点不好的回答")}</h3>
        {bad.length
          ? <BackstageTable testId="quality-bad" label={t("被点不好的回答")} columns={badColumns} rows={bad} rowKey={row => row.id} onOpen={row => open(row.id)} />
          : <p className="text-small text-muted-foreground">{t("还没有被点「不好」的回答。")}</p>}
      </section>
      <section aria-labelledby="quality-ruler" className="flex min-w-0 flex-col gap-2">
        <h2 id="quality-ruler" className="text-body font-medium text-ink">{t("尺子历次成绩")}</h2>
        <p className="text-small text-muted-foreground">{t("尺子是固定的一套真实问题，每次改动前后在影子环境里跑一遍；这里列出盒子上留下的每一次结果。")}</p>
        {runs.length
          ? <BackstageTable testId="quality-ruler" label={t("尺子历次成绩")} columns={runColumns} rows={runs} rowKey={row => row.id} />
          : <p className="text-small text-muted-foreground">{t("盒子上还没有尺子的结果。")}</p>}
        {errors.length > 0 && <p data-testid="quality-ruler-errors" role="note" className="text-caption text-muted-foreground">{t("这些结果读不出来")}{`：${errors.join("，")}`}</p>}
      </section>
    </>}
    <AnswerDrawer id={openId} onClose={() => setOpenId(null)} returnFocus={() => { if (opener.current?.isConnected) opener.current.focus(); }} />
  </div>;
}
