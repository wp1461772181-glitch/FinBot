export interface PublicMarkView {
  id: string;
  label: string;
  sentence: string;
  nameSpan: string;
  evidence: { ordinal: number | null; quote: string; completeness: "complete" | "excerpt" };
}

export declare const PUBLIC_MARK_GLYPH: string;
export declare const PUBLIC_MARK_ARIA: string;
export declare const PUBLIC_MARK_LABELS: { readonly quote: string; readonly quoteNoOrdinal: string; readonly excerpt: string };

export declare function normalizePublicMarks(items: unknown): PublicMarkView[];
export declare function attachPublicMarks(content: string | null | undefined, items: unknown): string;
export declare function parsePublicMarkHref(href: unknown): number | null;
export declare function publicMarkQuoteText(view: PublicMarkView | null | undefined, t?: (text: string) => string): string;
export declare function publicMarkOrdinal(view: PublicMarkView | null | undefined): number | null;
