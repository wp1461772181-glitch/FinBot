import { Suspense, lazy } from "react";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/Segmented";
import { BotAvatar } from "@/components/bot/BotAvatar";
import { BotBody } from "@/components/bot/BotBody";
import { Skeleton } from "@/components/state/Skeleton";
import { OptionalChunk } from "../../OptionalChunk";
import type { Bot } from "../../api/bots";
import { BLOUB_COLORS, BLOUB_SHAPES, pickLook, resolveLook, type BloubLook } from "../../bloub-look.mjs";
import { COLOR_BY_ID } from "../../bloub/skins";
import { SHAPE_LABELS, COLOR_LABELS } from "../../BloubCustomizer";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { useLocale } from "../../i18n";
import { DEFAULT_AVATAR, parseAvatar } from "../../orb.mjs";
import type { BotDraft } from "../../bot-settings-form.mjs";
import type { FormProps } from "./FormSections";

// The personality pickers and the rehearsal (A5): a chunk of their own, fetched when the section is in use.  They keep what is picked in this browser
// (nothing of it reaches the save bar), and the rehearsal's large preview is this section's preview: it shows the draft's shape and colour.
const PersonaStudio = lazy(() => import("@/components/bot/PersonaStudio"));

/** Same moment as the resting pose in bloub, so a tile shows the shape and face the way they will appear. */
const PREVIEW_AT = 1;

/** 外观与性格: robot or emoji, the shape and the colour (kept on the server, with the save bar), then the personality studio (kept in this browser). */
export function LookSection({ draft, update, disabled, bot, others, studio }: FormProps & { bot: Bot; others: ReadonlyArray<Bot>; studio: boolean }) {
  const { t } = useLocale();
  const isOrb = parseAvatar(draft.avatar ?? "", draft.name).kind === "bot";
  const shown: BloubLook = draft.look ?? resolveLook(draft.seed, draft.avatar, null, draft.name);
  const patch = (next: Partial<BotDraft>) => update({ ...draft, ...next });
  return <>
    <Segmented name="bot-avatar-kind" testid="avatar-kind" legend={t("头像")} value={isOrb ? "orb" : "emoji"} disabled={disabled}
      options={[{ value: "orb", label: t("机器人") }, { value: "emoji", label: t("自定义 emoji") }]}
      onChange={(value) => { if ((value === "orb") !== isOrb) patch({ avatar: value === "orb" ? DEFAULT_AVATAR : "" }); }} />
    {isOrb ? <>
      <Segmented name="bot-shape" testid="look-shape" legend={t("形状")} value={shown.shape} disabled={disabled} className="[&_[data-option]]:min-h-[84px] [&_[data-option]]:px-2"
        options={BLOUB_SHAPES.map((id: string) => ({ value: id, label: <span className="flex flex-col items-center gap-1"><BotBody size={52} shape={id} color={shown.color} frozenAt={PREVIEW_AT} /><span>{t(SHAPE_LABELS[id])}</span></span> }))}
        onChange={(id) => patch({ look: pickLook(shown, "shape", id) })} />
      <Segmented name="bot-color" testid="look-color" legend={t("颜色")} value={shown.color} disabled={disabled}
        options={BLOUB_COLORS.map((id: string) => ({ value: id, label: <span className="flex items-center gap-1.5"><span aria-hidden="true" className="size-4 rounded-full border border-line-strong" style={{ background: COLOR_BY_ID.get(id)?.hex }} /><span>{t(COLOR_LABELS[id])}</span></span> }))}
        onChange={(id) => patch({ look: pickLook(shown, "color", id) })} />
    </> : <Field>
      <FieldLabel htmlFor="bot-avatar">{t("头像")}</FieldLabel>
      <div className="flex items-center gap-3">
        <BotAvatar avatar={draft.avatar} name={draft.name || "·"} size={BOT_AVATAR_SIZE.emoji} />
        <Input id="bot-avatar" className="max-w-48" value={draft.avatar} maxLength={16} disabled={disabled} placeholder="📈" onChange={(e) => patch({ avatar: e.target.value })} />
      </div>
      <FieldDescription>{t("一个 emoji 或最多 16 个字符。")}</FieldDescription>
    </Field>}
    {studio && <OptionalChunk><Suspense fallback={<Skeleton className="h-64" />}>
      <PersonaStudio bot={bot} look={draft.look ?? null} others={others} emoji={!isOrb} />
    </Suspense></OptionalChunk>}
  </>;
}
