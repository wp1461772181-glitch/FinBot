type BotLike = { id: string; hidden?: boolean; is_default?: boolean; focus?: { companies?: Array<{ symbol: string; name?: string | null }> }; default_company?: { symbol: string; company: string | null } | null };
export function companyName(symbol: string, bots?: BotLike[]): string | null;
export function askBots<T extends BotLike>(symbol: string, bots?: T[]): { bots: T[]; following: boolean };
export function prepareAsk(input: { bot: BotLike; symbol: string; draftText: string; storage?: unknown }): { prefilled: boolean; line: string };
export function askDraft(symbol: string, options?: { about?: string; colon?: string }): string;
export function companyIsEmpty(counts: { prices: number | null; forecasts: number | null; materials: number | null; filings: number | null }): boolean;
