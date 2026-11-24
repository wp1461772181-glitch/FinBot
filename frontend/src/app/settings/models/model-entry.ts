import { catalogName, priceText, type CatalogEntryDraft } from "../../../catalog-form.mjs";
import { CATALOG } from "../../../model-profiles.mjs";

/** A blank entry for 添加模型: the first provider of the list, named after it, the default when the catalog is empty. */
export const blankEntry = (taken: string[]): CatalogEntryDraft => ({ name: catalogName(CATALOG[0].provider, taken), display_name: "", provider: CATALOG[0].provider, model: "", base_url: CATALOG[0].baseUrl, key_mode: "vault", api_key: "", key_env: "", is_default: taken.length === 0, price_input: "", price_output: "", price_cache_read: "", price_cache_write: "", editing: null });
/** The entry of 编辑: the stored record's fields; the key is never read back, so the key box starts empty. */
export const editEntry = (m: NonNullable<CatalogEntryDraft["editing"]>): CatalogEntryDraft => ({ name: m.name, display_name: m.display_name, provider: m.provider, model: m.model, base_url: m.base_url ?? "", key_mode: m.key_source, api_key: "", key_env: m.key_env ?? "", is_default: m.is_default, price_input: priceText(m.price_input), price_output: priceText(m.price_output), price_cache_read: priceText(m.price_cache_read), price_cache_write: priceText(m.price_cache_write), editing: m });
