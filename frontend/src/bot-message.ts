// The error text a bot or catalog request shows: the server's message, or the fallback, through the phrase catalog.
// Moved as-is in P3.1 (it was a private helper of BotPages.tsx; three files use it now).
import { translatePhrase } from "./i18n";

export const message = (error: unknown, fallback: string) => translatePhrase(error instanceof Error ? error.message : fallback);
