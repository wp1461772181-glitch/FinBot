export function isNewHash(hash: unknown): boolean;
export function legacyHashToPath(hash: string, options?: { lastSymbol?: string | null }): string | null;
export function normalizeHash(hash: string, options?: { lastSymbol?: string | null }): string | null;
export function appHref(hash: string, options?: { lastSymbol?: string | null }): string;
