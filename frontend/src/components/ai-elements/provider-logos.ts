// The provider logos shipped with the app (src/assets/provider-logos/*.svg, from models.dev; see THIRD_PARTY_NOTICES.md).  Only the files' URLs are
// bundled (`?no-inline`: even the small ones stay files, fetched when an <img> shows them), never an external address.
const files = import.meta.glob<string>("../../assets/provider-logos/*.svg", { query: "?no-inline", import: "default", eager: true });

const byKey = new Map(Object.entries(files).map(([path, url]) => [path.replace(/^.*\/(.+)\.svg$/, "$1"), url]));

/** The URL of a logo key (a key of LOGO_KEYS); anything else, or null, is the generic mark. */
export function logoUrl(key: string | null | undefined): string {
  return (key ? byKey.get(key) : undefined) ?? byKey.get("generic") ?? "";
}
