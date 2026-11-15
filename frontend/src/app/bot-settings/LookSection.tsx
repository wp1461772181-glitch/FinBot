import { Suspense, lazy } from "react";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/Segmented";
import { BotAvatar } from "@/components/bot/BotAvatar";
import { LookPicker } from "@/components/bot/LookPicker";
import { Skeleton } from "@/components/state/Skeleton";
import { OptionalChunk } from "../../OptionalChunk";
import type { Bot } from "../../api/bots";
import { resolveLook, type BloubLook } from "../../bloub-look.mjs";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { useLocale } from "../../i18n";
import { DEFAULT_AVATAR, parseAvatar } from "../../orb.mjs";
import type { BotDraft } from "../../bot-settings-form.mjs";
import type { FormProps } from "./FormSections";

// The personality pickers and the rehearsal (A5): a chunk of their own, fetched when the section is in use.  They keep what is picked in this browser
// (nothing of it reaches the save bar), and the rehearsal's large preview is this section's preview: it shows the draft's shape and colour.
const PersonaStudio = lazy(() => import("@/components/bot/PersonaStudio"));

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
      <LookPicker look={shown} onChange={(next) => patch({ look: next })} disabled={disabled} />
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
