// Per-bot avatar customiser: the shape / expression / colour pickers of bloub's Customise panel (jeremy-prt/bloub,
// src/components/Customizer.vue + BotTile.vue, MIT — see THIRD_PARTY_NOTICES.md), in React and in this app's theme tokens.
// Every tile is a still frame of the bot as it would look with that choice; the live preview is the caller's (a hero above).
import { BloubAvatar } from "./BloubAvatar";
import { BLOUB_COLORS, BLOUB_EXPRESSIONS, BLOUB_SHAPES, pickLook, type BloubLook } from "./bloub-look.mjs";
import { COLOR_BY_ID } from "./bloub/skins";
import { useLocale } from "./i18n";

/** Phrases are Chinese keys of the app's i18n catalog (en-US.json); the ids are bloub's. */
export const SHAPE_LABELS: Record<string, string> = { cercle: "圆形", galet: "卵石", squircle: "圆角方形", capsule: "胶囊", triangle: "三角形", hexagone: "六边形", nuage: "云朵", goutte: "水滴" };
export const COLOR_LABELS: Record<string, string> = { encre: "墨黑", creme: "奶油白", brun: "棕色", rouge: "红色", orange: "橙色", ambre: "琥珀色", vert: "绿色", turquoise: "青绿色", bleu: "蓝色", violet: "紫色", rose: "粉色", gris: "灰色" };
export const EXPRESSION_LABELS: Record<string, string> = { neutre: "平静", attentif: "专注", surpris: "惊讶", excite: "兴奋", heureux: "开心", hilare: "大笑", colere: "生气", triste: "难过", effraye: "害怕", mefiant: "怀疑", confus: "困惑", curieux: "好奇", fier: "得意", timide: "羞怯", blase: "无趣", somnolent: "困倦" };

/** Same moment as the resting pose in bloub, so a tile shows the shape and face the way they will appear. */
const PREVIEW_AT = 1;

export function BloubCustomizer({ look, onChange, disabled }: { look: BloubLook; onChange: (next: BloubLook) => void; disabled?: boolean }) {
  const { t } = useLocale();
  const tile = (field: "shape" | "expression", id: string, label: string, tileLook: BloubLook) =>
    <button key={id} type="button" className="bloub-tile" disabled={disabled} aria-pressed={look[field] === id} aria-label={label} onClick={() => onChange(pickLook(look, field, id))}>
      <BloubAvatar size={52} shape={tileLook.shape} color={tileLook.color} expression={tileLook.expression} frozenAt={PREVIEW_AT} />
      <span>{label}</span>
    </button>;
  return <div className="bloub-customizer">
    <h3>{t("形状")}</h3>
    <div className="bloub-grid is-4">{BLOUB_SHAPES.map(id => tile("shape", id, t(SHAPE_LABELS[id]), { ...look, shape: id }))}</div>
    <h3>{t("表情")}</h3>
    <div className="bloub-grid is-4">{BLOUB_EXPRESSIONS.map(id => tile("expression", id, t(EXPRESSION_LABELS[id]), { ...look, expression: id }))}</div>
    <h3>{t("颜色")}</h3>
    <div className="bloub-grid is-6">{BLOUB_COLORS.map(id =>
      <button key={id} type="button" className="bloub-swatch" disabled={disabled} aria-pressed={look.color === id} aria-label={t(COLOR_LABELS[id])} title={t(COLOR_LABELS[id])} onClick={() => onChange(pickLook(look, "color", id))}>
        <span style={{ background: COLOR_BY_ID.get(id)?.hex }} />
      </button>)}</div>
  </div>;
}
