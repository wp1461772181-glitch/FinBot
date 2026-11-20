// "外观与性格" of one bot, below the shape and colour pickers (design 4.3): the personality pickers and the rehearsal.  Loaded on demand
// (the bot settings page, P5.1, holds it).
import { useLocale } from "../../i18n";
import type { BloubLook } from "../../bloub-look.mjs";
import { PersonaPicker } from "./PersonaPicker";
import { Rehearsal, type StudioBot } from "./Rehearsal";

export default function PersonaStudio({ bot, look, others, emoji = false }: { bot: StudioBot; look?: BloubLook | null; others?: ReadonlyArray<StudioBot>; emoji?: boolean }) {
  const { t } = useLocale();
  return (
    <section data-slot="persona-studio" aria-labelledby="persona-studio-title" className="grid gap-4 border-t border-line pt-4 text-ink">
      <h3 id="persona-studio-title" className="m-0 text-body font-semibold">{t("性格与试演台")}</h3>
      <PersonaPicker bot={bot} />
      {emoji && <p className="m-0 text-small text-muted-foreground">{t("这个 bot 用的是 emoji 头像；试演台用机器人形象演示它的性格。")}</p>}
      <Rehearsal bot={bot} look={look} others={others ?? []} />
    </section>
  );
}
