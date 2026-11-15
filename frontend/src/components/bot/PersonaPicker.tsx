// "外观与性格": the personality pickers of one bot (design 4.3 / 6.4): archetype, tempo, easing, aura variant, where the current values come from,
// and 恢复默认.  What is picked is kept in THIS browser only (D4: the backend's `look` check rejects extra keys, so nothing here is sent anywhere) and applies
// at once to every avatar and line of the bot; it is not part of the profile form, so the form's save bar does not light up for it.
import { useMemo } from "react";
import { useLocale } from "../../i18n";
import {
  AURA_VARIANTS, ARCHETYPES, EASINGS, TEMPO_STEPS, clearOverrides, derivePersona, personaBasis, readVolatility, tempoStepOf, trackedSymbol, writeOverrides,
  type Archetype, type Easing, type PersonaBot, type PersonaOverrides
} from "../../bot-persona.mjs";
import { Segmented } from "../Segmented";
import { useOverrides, usePersona } from "./use-persona";

const storage = () => { try { return window.localStorage; } catch { return null; } };

export const ARCHETYPE_NAMES: Record<Archetype, string> = { lead: "主理", tracker: "追踪", sentinel: "哨兵", reader: "审读", generalist: "通才" };
export const ARCHETYPE_HINTS: Record<Archetype, string> = {
  lead: "总入口：刻度环，稳。", tracker: "盯一家公司：看波动定快慢。", sentinel: "盯新闻：快讯条和信号弧。", reader: "读财报：逐行核对的页行。", generalist: "没有特别倾向：环绕的小点。"
};
const TEMPO_NAMES = { calm: "沉稳", standard: "标准", brisk: "轻快", rapid: "迅捷" } as const;
const EASING_NAMES: Record<Easing, string> = { smooth: "平滑", spring: "弹性", step: "步进" };
export const VARIANT_NAMES: Record<string, string> = {
  ticks: "刻度环", gauge: "仪表弧", pips: "点阵", "speed-lines": "速度线", halo: "呼吸光环", reticle: "准星扫描",
  ticker: "快讯条", morse: "信号点", beacon: "信号弧", "page-lines": "页行", "margin-ticks": "页边刻度", underline: "下划线",
  "orbit-dots": "环绕点", "twin-dots": "双点", trio: "三点"
};
const RULE_TEXT = {
  default: "默认 bot → 主理", news_monitor: "模板「新闻监控」→ 哨兵", earnings_reader: "模板「财报解读」→ 审读",
  company: "只关注一家公司 / 模板「公司研究员」→ 追踪", none: "没有命中模板或关注公司 → 通才，节奏与光环按 bot id 取值"
} as const;
const BAND_TEXT = { fast: "近 60 个交易日波动率高 → 迅捷", standard: "近 60 个交易日波动率适中 → 标准", calm: "近 60 个交易日波动率低 → 沉稳" } as const;

export function PersonaPicker({ bot }: { bot: PersonaBot & { id: string; name: string } }) {
  const { t } = useLocale();
  const persona = usePersona(bot);
  const overrides = useOverrides(bot.id);
  const symbol = trackedSymbol(bot);
  const volatility = symbol ? readVolatility(storage(), bot.id, symbol) : null;
  const base = useMemo(() => derivePersona(bot, { volatility }), [bot, volatility]);
  const basis = personaBasis(bot, { volatility, overrides });
  const fixedLead = Boolean(bot.is_default);
  const variants = AURA_VARIANTS[persona.archetype];

  /** Keep the pick; a value that is the one the bot would have anyway is not an override at all (so "你改过" goes away when everything is back). */
  const pick = (patch: PersonaOverrides) => {
    const next: PersonaOverrides = { ...overrides, ...patch };
    if ("archetype" in patch) delete next.auraVariant; // a variant belongs to its archetype
    if (next.archetype === base.archetype) delete next.archetype;
    const baseline = derivePersona(bot, { volatility, overrides: next.archetype ? { archetype: next.archetype } : {} }); // the same archetype with nothing else changed
    if (next.tempo === baseline.tempo) delete next.tempo;
    if (next.easing === baseline.easing) delete next.easing;
    if (next.auraVariant === baseline.auraVariant) delete next.auraVariant;
    writeOverrides(storage(), bot.id, next);
  };

  const sourceLine = (() => {
    const was = basis.kind === "preset" ? t("这是 {name} 的预设。").replace("{name}", basis.name)
      : [t(RULE_TEXT[basis.rule]), basis.band ? t(BAND_TEXT[basis.band]) : ""].filter(Boolean).join(" · ");
    if (basis.overridden) return `${t("你改过")} · ${t("原本")}：${was}`;
    return basis.kind === "preset" ? was : `${t("自动推导")}：${was}`;
  })();

  return (
    <div data-slot="persona-picker" data-archetype={persona.archetype} data-source={persona.source} className="grid gap-3">
      <Segmented<Archetype> name={`persona-archetype-${bot.id}`} testid="persona-archetype" legend={t("性格原型")} value={persona.archetype} disabled={fixedLead}
        onChange={(value) => pick({ archetype: value })} options={ARCHETYPES.map((value: Archetype) => ({ value, label: t(ARCHETYPE_NAMES[value]) }))} />
      <p data-testid="persona-archetype-hint" className="m-0 text-small text-muted-foreground">
        {fixedLead ? t("默认 bot 的原型固定为「主理」：没指明给谁的消息都进它，所以它是其他 bot 性格的参照，不能改。") : t(ARCHETYPE_HINTS[persona.archetype])}
      </p>
      <Segmented<keyof typeof TEMPO_NAMES> name={`persona-tempo-${bot.id}`} testid="persona-tempo" legend={t("节奏")} value={tempoStepOf(persona.tempo)}
        onChange={(id) => pick({ tempo: TEMPO_STEPS.find((step) => step.id === id)!.value })} options={TEMPO_STEPS.map((step) => ({ value: step.id, label: t(TEMPO_NAMES[step.id]) }))} />
      <Segmented<Easing> name={`persona-easing-${bot.id}`} testid="persona-easing" legend={t("缓动")} value={persona.easing}
        onChange={(value) => pick({ easing: value })} options={EASINGS.map((value: Easing) => ({ value, label: t(EASING_NAMES[value]) }))} />
      <Segmented<string> name={`persona-aura-${bot.id}`} testid="persona-aura" legend={t("光环变体")} value={persona.auraVariant}
        onChange={(value) => pick({ auraVariant: value })} options={variants.map((value: string) => ({ value, label: t(VARIANT_NAMES[value] ?? value) }))} />
      <p data-testid="persona-source" data-kind={basis.overridden ? "override" : basis.kind} className="m-0 text-small text-ink">
        <span className="font-medium">{t("来源")}：</span>{sourceLine}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" data-testid="persona-reset" disabled={!basis.overridden} onClick={() => { clearOverrides(storage(), bot.id); }}
          className="cursor-pointer rounded-sm border border-line bg-surface px-2.5 py-1 text-small text-ink max-sm:min-h-11 hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:bg-surface">
          {t("恢复默认")}
        </button>
      </div>
      <p data-testid="persona-local-note" className="m-0 text-small text-muted-foreground">
        {t("性格与节奏只保存在这台设备的这个浏览器里，不会同步到别的设备，也不属于下面的「保存」：改了就生效，保存栏不会亮。")}
      </p>
    </div>
  );
}
