/** A translated sentence with its `{name}` places filled in (the translation tables hold the sentence with the places in it; the repo's other pages do the same with `.replace`). */
export function fill(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole));
}
