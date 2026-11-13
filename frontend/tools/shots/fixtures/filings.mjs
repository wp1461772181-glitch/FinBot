// SEC filing inventory (the overview's 官方申报 list) per symbol.
import { daysAgo } from "./common.mjs";

const FORMS = [["10-Q", 14, "季度报告"], ["8-K", 21, "当前报告"], ["10-K", 75, "年度报告"], ["10-Q", 105, "季度报告"], ["8-K", 120, "当前报告"]];
export function filingInventory(symbol) {
  const base = symbol.charCodeAt(0) * 1000;
  return { symbol, filings: FORMS.map(([form, ago], index) => ({
    id: `fl000000-0000-4000-8000-${String(base + index).padStart(12, "0")}`,
    accession_number: `0000000000-26-${String(base % 1000000 + index).padStart(6, "0")}`, form, filed_at: daysAgo(ago).slice(0, 10), accepted_at: daysAgo(ago),
    primary_document: `${symbol.toLowerCase()}-${form.toLowerCase()}.htm`, source_url: `https://www.sec.gov/Archives/edgar/data/0000000/${symbol.toLowerCase()}-${form.toLowerCase()}-${index}.htm`,
    observed_at: daysAgo(ago - 1), source: "sec_edgar", review_status: index === 0 ? "accepted" : "pending_review", human_review_note: null, reviewed_at: null,
    content_status: index < 3 ? "fetched" : "not_fetched", content_observed_at: index < 3 ? daysAgo(ago - 1) : null, content_truncated: false, content_error: null })) };
}
