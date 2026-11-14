import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type zhPhrases from "./locales/zh-CN.json";

export type Locale = "zh-CN" | "en-US";
export type PhraseKey = typeof zhPhrases[number];

const STORAGE_KEY = "market-evidence-agent:locale:v1";
type EnglishCatalog = Record<PhraseKey, string>;

// The English catalog is a chunk of its own: a session in Chinese never downloads it.  translatePhrase stays synchronous, so
// until the chunk is in (a first switch to English, or a failed download) a phrase shows as its key, which is the Chinese text.
let englishCatalog: EnglishCatalog | null = null;
let englishLoading: Promise<void> | null = null;

export function loadEnglishCatalog(): Promise<void> {
  englishLoading ??= import("./locales/en-US.json").then((module) => {
    const catalog: EnglishCatalog = module.default;
    englishCatalog = catalog;
  }, (error: unknown) => { englishLoading = null; throw error; });
  return englishLoading;
}

/** Called before the first render: a reader whose saved language is English gets the catalog first, so no Chinese flashes by. */
export function preloadSavedLocale(): Promise<void> {
  return readSavedLocale() === "en-US" ? loadEnglishCatalog().catch(() => undefined) : Promise.resolve();
}

type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (text: string) => string;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readSavedLocale);
  // Bumped when the English catalog arrives, so `t` changes identity and every reader of it draws again.
  const [catalogReady, setCatalogReady] = useState(englishCatalog !== null);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
    try { window.localStorage.setItem(STORAGE_KEY, nextLocale); } catch { /* Locale still applies for this session. */ }
  }, []);

  useEffect(() => {
    if (locale !== "en-US" || englishCatalog) return;
    let live = true;
    loadEnglishCatalog().then(() => { if (live) setCatalogReady(true); }, () => { /* offline: the phrases stay as their keys */ });
    return () => { live = false; };
  }, [locale]);

  const t = useCallback((text: string) => {
    return translatePhrase(text, locale);
  }, [locale, catalogReady]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const value = useContext(LocaleContext);
  if (!value) throw new Error("useLocale must be used inside LocaleProvider");
  return value;
}

/** Render an exact static UI phrase through the active locale dictionary. */
export function Tx({ text }: { text: string }) {
  const { t } = useLocale();
  return <>{t(text)}</>;
}

export function formatDateTime(value: string | Date, locale: Locale, timeZone = "UTC") {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.valueOf())) return String(value);
  return new Intl.DateTimeFormat(locale, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone, timeZoneName: "short",
  }).format(date);
}

export function formatDate(value: string | Date, locale: Locale, timeZone = "UTC") {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.valueOf())) return String(value);
  return new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "numeric", timeZone }).format(date);
}

export function formatNumber(value: number, locale: Locale, options: Intl.NumberFormatOptions = {}) {
  return new Intl.NumberFormat(locale, options).format(value);
}

export function translatePhrase(text: string, locale: Locale = getLocalePreference()): string {
  if (locale === "zh-CN") return text;
  return englishCatalog?.[text as PhraseKey] ?? text;
}

function readSavedLocale(): Locale {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en-US" || saved === "zh-CN") return saved;
  } catch { /* Storage is optional; Chinese remains the default. */ }
  return "zh-CN";
}

/** Reads the same persisted preference for non-component date-format helpers. */
export function getLocalePreference(): Locale {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en-US" || saved === "zh-CN") return saved;
  } catch { /* Fall back to the default locale. */ }
  return "zh-CN";
}
