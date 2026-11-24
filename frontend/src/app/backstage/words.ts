import { useMemo } from "react";
import type { Words } from "../../backstage-view.mjs";
import { colon, comma, parens, useLocale } from "../../i18n";

/** What the view model puts its sentences together from, in the interface language: the translation function and the punctuation. */
export function useWords(): Words {
  const { t, locale } = useLocale();
  return useMemo(() => ({ t, colon: colon(locale), comma: comma(locale), list: comma(locale), parens: (value: string) => parens(value, locale) }), [t, locale]);
}
