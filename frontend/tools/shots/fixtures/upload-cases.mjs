// The upload form's cases (P6.3): the same table drives the node test of the rules (scripts/evidence-upload.test.mjs) and the smoke check on the page.
// Each case changes one thing of a form that is otherwise valid; the old form's answer to every case is recorded in material-bodies-baseline.json
// (`uploadRules.<name>`: whether it let the case through, and what it then sent).  A file is { name, mimeType }; the smoke check gives it bytes.
export const VALID = { file: { name: "report.pdf", mimeType: "application/pdf" }, title: "权威媒体报道", url: "https://example.com/a", published: "2026-11-10T09:30", stars: 3, impact: "medium", reason: "一手采访" };
const f = (name, mimeType) => ({ file: { name, mimeType } });
export const CASES = [
  ["valid", {}], ["no-file", { file: null }],
  ["file-exe", f("x.exe", "application/octet-stream")], ["file-csv", f("a.csv", "text/csv")], ["file-TXT-upper", f("NOTE.TXT", "application/octet-stream")],
  ["file-md", f("n.md", "")], ["file-markdown", f("n.markdown", "")], ["file-noext-by-mime", f("noext", "text/plain")], ["file-doc-with-pdf-mime", f("a.doc", "application/pdf")],
  ["title-empty", { title: "" }], ["title-spaces", { title: "   " }], ["title-240", { title: "题".repeat(240) }],
  ["url-empty", { url: "" }], ["url-http", { url: "http://example.com/a" }], ["url-ftp", { url: "ftp://example.com/a" }], ["url-text", { url: "not a url" }], ["url-https", { url: "https://a.b/c?d=1" }],
  ["published-empty", { published: "" }],
  ["reason-empty", { reason: "" }], ["reason-spaces", { reason: "   " }], ["reason-1000", { reason: "因".repeat(1000) }],
  ["stars-1", { stars: 1 }], ["stars-5", { stars: 5 }], ["impact-low", { impact: "low" }], ["impact-high", { impact: "high" }],
  ["title-padded", { title: "  两端空格  " }], ["reason-padded", { reason: "  两端空格  " }],
];
/** The mime type a browser gives a file by its extension when the case names none (what the old form's run recorded). */
export const guessedType = (name) => (/\.(md|markdown)$/i.test(name) ? "text/markdown" : /\.txt$/i.test(name) ? "text/plain" : /\.pdf$/i.test(name) ? "application/pdf" : "");
