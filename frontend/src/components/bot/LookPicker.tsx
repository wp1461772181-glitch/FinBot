// The shape and colour pickers of a bot's look (the 8 shapes × 12 colours of the bloub catalog; jeremy-prt/bloub, MIT — see THIRD_PARTY_NOTICES.md).  One
// component for the two places that choose a look: the bot settings page (外观与性格) and the new-bot dialog (P5.2).  Every shape tile is a still frame of
// the bot as it would look with that choice; the live preview is the caller's.  Radios underneath (Segmented), so the arrow keys, Tab and a screen reader
// work as they do everywhere.
import { BotBody } from "./BotBody";
import { Segmented } from "../Segmented";
import { BLOUB_COLORS, BLOUB_SHAPES, pickLook, type BloubLook } from "../../bloub-look.mjs";
import { COLOR_BY_ID } from "../../bloub/skins";
import { useLocale } from "../../i18n";

/** Phrases are Chinese keys of the app's i18n catalog (en-US.json); the ids are bloub's. */
export const SHAPE_LABELS: Record<string, string> = { cercle: "圆形", galet: "卵石", squircle: "圆角方形", capsule: "胶囊", triangle: "三角形", hexagone: "六边形", nuage: "云朵", goutte: "水滴" };
export const COLOR_LABELS: Record<string, string> = { encre: "墨黑", creme: "奶油白", brun: "棕色", rouge: "红色", orange: "橙色", ambre: "琥珀色", vert: "绿色", turquoise: "青绿色", bleu: "蓝色", violet: "紫色", rose: "粉色", gris: "灰色" };

/** Same moment as the resting pose in bloub, so a tile shows the shape and face the way they will appear. */
const PREVIEW_AT = 1;

export function LookPicker({ look, onChange, disabled, compact = false, name = "bot", testidPrefix = "" }: {
  look: BloubLook; onChange: (next: BloubLook) => void; disabled?: boolean;
  /** Smaller tiles and colour dots without their words (the dialog's one screen); the words stay as the dot's name for a screen reader. */
  compact?: boolean;
  /** The radio groups' name base (two pickers on one page must not share a group) and the prefix of the test ids. */
  name?: string; testidPrefix?: string;
}) {
  const { t } = useLocale();
  return <>
    <Segmented name={`${name}-shape`} testid={`${testidPrefix}look-shape`} legend={t("形状")} value={look.shape} disabled={disabled}
      className={compact ? "[&_[data-option]]:min-h-[68px] [&_[data-option]]:px-1.5" : "[&_[data-option]]:min-h-[84px] [&_[data-option]]:px-2"}
      options={BLOUB_SHAPES.map((id: string) => ({ value: id, label: <span className="flex flex-col items-center gap-1"><BotBody size={compact ? 40 : 52} shape={id} color={look.color} frozenAt={PREVIEW_AT} /><span>{t(SHAPE_LABELS[id])}</span></span> }))}
      onChange={(id) => onChange(pickLook(look, "shape", id))} />
    <Segmented name={`${name}-color`} testid={`${testidPrefix}look-color`} legend={t("颜色")} value={look.color} disabled={disabled}
      className={compact ? "[&_[data-option]]:px-1.5" : undefined}
      options={BLOUB_COLORS.map((id: string) => ({ value: id, label: <span className="flex items-center gap-1.5" title={compact ? t(COLOR_LABELS[id]) : undefined}>
        <span aria-hidden="true" className="size-4 rounded-full border border-line-strong" style={{ background: COLOR_BY_ID.get(id)?.hex }} />
        <span className={compact ? "sr-only" : undefined}>{t(COLOR_LABELS[id])}</span></span> }))}
      onChange={(id) => onChange(pickLook(look, "color", id))} />
  </>;
}
