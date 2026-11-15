import { Tx, useLocale } from "./i18n";
import type { Dispatch, SetStateAction } from "react";
import type { V2RevisionCandidates } from "./api/forecast-v2";
import type { V2TimelineEntry } from "./types";
import { formatTime } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";

export type RevisionSourceOption = {
  key: string;
  source_type: string;
  source_id: string;
  label: string;
  publishedAt: string | null;
  observedAt: string | null;
  revisionType: string;
};

export function ForecastRevisionForm({ versions, rootIsRevisable, jobActive, revisionOpen, setRevisionOpen, revisionDisabledReason, parentVersionId, setParentVersionId, selectedSourceKeys, setSelectedSourceKeys, revisionCandidates, revisionCandidatesData, revisionSourceOptions, canCreateRevision, onCreate }: {
  versions: V2TimelineEntry[];
  rootIsRevisable: boolean;
  jobActive: boolean;
  revisionOpen: boolean;
  setRevisionOpen: Dispatch<SetStateAction<boolean>>;
  revisionDisabledReason: string | null;
  parentVersionId: string;
  setParentVersionId: (id: string) => void;
  selectedSourceKeys: string[];
  setSelectedSourceKeys: (keys: string[]) => void;
  revisionCandidates: ResourceState<V2RevisionCandidates> | null;
  revisionCandidatesData: V2RevisionCandidates | null;
  revisionSourceOptions: RevisionSourceOption[];
  canCreateRevision: boolean;
  onCreate: () => void;
}) {
  const { t } = useLocale();
  return <>
      <section className="v2-revision-entry" aria-labelledby="v2-revision-title">
        <div>
          <p className="section-label">{<Tx text={"人工核验入口"} />}</p>
          <h3 id="v2-revision-title">{<Tx text={"用一条新材料发起修订"} />}</h3>
          <p>{<Tx text={"系统会在服务端检查材料的发布时点、观察时点、来源状态变化和固定目标合同；未来材料仍会被拒绝。提交成功只代表已入队，原版本保持不变。"} />}</p>
        </div>
        <button className="secondary-action" type="button" onClick={() => setRevisionOpen((open) => !open)} disabled={!versions.length || !rootIsRevisable || jobActive}>
          {revisionOpen ? t("收起修订") : t("选择版本与材料")}
        </button>
      </section>

      {revisionDisabledReason && <p className="v2-root-warning" role="status">{revisionDisabledReason}</p>}

      {revisionOpen && <section className="v2-revision-form" aria-label={t("创建手动修订")}>
        <label>{<Tx text={"修订哪一个预测版本"} />}<select value={parentVersionId} onChange={(event) => { setParentVersionId(event.target.value); setSelectedSourceKeys([]); }}>
            <option value="">{<Tx text={"默认最新版本"} />}</option>
            {versions.map((version) => <option value={version.id} key={version.id}>{t("第")} {version.version_no} {t("版")} · {formatTime(version.decision_at)}</option>)}
          </select>
        </label>
        <div className="v2-revision-sources-field">
          <div className="v2-revision-sources-header">
            <span>{<Tx text={"用于本次修订的材料"} />}（{t("已选")} {selectedSourceKeys.length} / {t("最多 10 份")}）</span>
            {revisionSourceOptions.length > 0 && (
              <div className="v2-selection-actions">
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setSelectedSourceKeys(revisionSourceOptions.slice(0, 10).map((s) => s.key))}
                >
                  {t("全选前10项")}
                </button>
                {selectedSourceKeys.length > 0 && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setSelectedSourceKeys([])}
                  >
                    {t("清空已选")}
                  </button>
                )}
              </div>
            )}
          </div>
          {revisionCandidates?.kind === "error" ? (
            <p className="v2-hint-text" role="status">{t("无法读取可选修订材料，系统会继续重试：")}{revisionCandidates.message}</p>
          ) : !revisionCandidatesData ? (
            <p className="v2-hint-text">{<Tx text={"正在读取可选修订材料…"} />}</p>
          ) : revisionCandidatesData.expired ? (
            <p className="v2-hint-text">{t(revisionCandidatesData.target_end_date === null ? "该预测的目标合同无效，只能查看历史版本。" : "该预测的目标已到期，只能查看历史版本。")}</p>
          ) : revisionSourceOptions.length === 0 ? (
            <>
              <p className="v2-hint-text">{<Tx text={"当前没有可用于修订的材料。可选的是：预测后 7 天内发布的新材料，预测前 30 天内发布、预测之后才收录的材料，或预测前已入库但本版未采用的材料。"} />}</p>
              {revisionCandidatesData.excluded.length > 0 && (
                <ul className="v2-revision-excluded">
                  {revisionCandidatesData.excluded.map((item) => (
                    <li key={`${item.source_type}:${item.source_id}`}>
                      <span className="v2-source-title">{item.title}</span>
                      <span className="v2-source-meta-row">{item.reason_text ?? item.reason}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <div className="v2-revision-sources-list">
              {revisionSourceOptions.map((source) => {
                const key = source.key;
                const isChecked = selectedSourceKeys.includes(key);
                const tagColor = source.revisionType === "new"
                  ? "badge-new"
                  : source.revisionType === "backfilled" || source.revisionType === "preexisting"
                    ? "badge-backfilled"
                    : "badge-updated";
                const typeLabel = source.revisionType === "new"
                  ? t("新发布材料")
                  : source.revisionType === "backfilled"
                    ? t("过往补充材料")
                    : source.revisionType === "preexisting"
                      ? t("预测前已入库、本版未采用")
                      : source.revisionType === "reanalyzed"
                        ? t("新完成分析")
                        : t("来源状态更新");
                return (
                  <label key={key} className={`v2-revision-source-item ${isChecked ? "is-selected" : ""}`}>
                    <input
                      type="checkbox"
                      checked={isChecked}
                      disabled={!isChecked && selectedSourceKeys.length >= 10}
                      onChange={(e) => {
                        if (e.target.checked) {
                          if (selectedSourceKeys.length < 10) setSelectedSourceKeys([...selectedSourceKeys, key]);
                        } else {
                          setSelectedSourceKeys(selectedSourceKeys.filter((k) => k !== key));
                        }
                      }}
                    />
                    <div className="v2-source-content">
                      <div className="v2-source-title-row">
                        <span className={`revision-type-badge ${tagColor}`}>{typeLabel}</span>
                        <span className="v2-source-title">{source.label}</span>
                      </div>
                      <div className="v2-source-meta-row">
                        <span>{t("发布时间")}：{formatTime(source.publishedAt)}</span>
                        {source.observedAt && <span> · {t("入库时间")}：{formatTime(source.observedAt)}</span>}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          )}
        </div>
        <div className="v2-form-footer">
          <button className="primary-action" type="button" onClick={onCreate} disabled={!canCreateRevision || !rootIsRevisable}>
            {<Tx text={"创建人工修订任务"} />}{selectedSourceKeys.length > 0 ? ` (${selectedSourceKeys.length})` : ""}
          </button>
        </div>
      </section>}
  </>;
}
