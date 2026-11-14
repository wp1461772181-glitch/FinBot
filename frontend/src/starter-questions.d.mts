export type Starter = { id: string; phrase: string; symbol: string | null; text: string };
type BotLike = { template?: string; focus?: { companies?: { symbol?: string }[] } | null; default_company?: { symbol?: string } | null } | null | undefined;
export function botSymbol(bot: BotLike): string | null;
export function starterQuestions(bot: BotLike): Starter[];
export const STARTER_PHRASES: string[];
