import { ArrowUpRight } from "lucide-react";
import { LiveBotOrb } from "../../LiveBotOrb";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { starterQuestions } from "../../starter-questions.mjs";
import type { Bot } from "../../api";
import { useLocale } from "../../i18n";

const starterClass = "inline-flex min-h-11 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-left text-small text-ink-2 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring sm:min-h-9";

/**
 * A line that has not spoken yet (design 4.2, 空): the bot at large size doing its arrival, its title and what it is for, the companies it watches,
 * and three questions to start from.  A question fills the composer and sends nothing: the reader edits it or sends it.
 */
export default function EmptyChat({ bot, verified, onPick }: { bot?: Bot | null; verified: boolean; onPick: (text: string) => void }) {
  const { t } = useLocale();
  const companies = bot?.focus?.companies?.map((company) => company.symbol).filter(Boolean) ?? [];
  const starters = verified ? starterQuestions(bot) : [];
  return <div data-testid="welcome" className="mx-auto flex w-full max-w-[760px] flex-col items-center gap-4 py-10 text-center">
    {bot
      ? <>
        <span data-testid="welcome-avatar" className="flex [&_.bot-avatar]:h-[var(--avatar)] [&_.bot-avatar]:w-[var(--avatar)]" style={{ "--avatar": `${BOT_AVATAR_SIZE.hero}px` } as React.CSSProperties}>
          <LiveBotOrb key={bot.id} avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} arrivalKey={`${bot.id}:hero`} size={BOT_AVATAR_SIZE.hero} chatState="idle" messages={[]} />
        </span>
        <div className="flex max-w-[34rem] flex-col gap-1">
          {bot.title && <p className="text-title-s text-ink">{bot.title}</p>}
          {bot.description && <p className="text-body text-muted-foreground">{bot.description}</p>}
        </div>
        {companies.length > 0 && <ul data-testid="welcome-companies" aria-label={t("关注公司")} className="flex flex-wrap justify-center gap-1.5">
          {companies.map((symbol) => <li key={symbol} className="rounded-full border border-line bg-sunken px-2.5 py-0.5 font-mono text-caption text-ink-2">{symbol}</li>)}
        </ul>}
        {!verified && <p className="text-body text-muted-foreground">{t("登录个人聊天后才能对话：模型由服务器模型目录提供。")}</p>}
      </>
      : <>
        <h2 className="text-title-m text-ink">{t("从一个问题开始")}</h2>
        <p className="text-body text-muted-foreground">{t(verified ? "连接已就绪，可以输入问题或选择下方建议。" : "登录个人聊天后才能对话：模型由服务器模型目录提供。")}</p>
      </>}
    {starters.length > 0 && <div data-testid="starters" role="group" aria-label={t("起手问题")} className="flex flex-wrap justify-center gap-2">
      {starters.map((starter) => {
        const text = starter.symbol ? t(starter.phrase).replace("{symbol}", starter.symbol) : t(starter.phrase);
        return <button type="button" key={starter.id} data-testid="starter" onClick={() => onPick(text)} className={starterClass}>{text}<ArrowUpRight className="size-3.5 shrink-0" aria-hidden="true" /></button>;
      })}
    </div>}
  </div>;
}
