export function citationOrdinal(citation, index) {
  return citation?.ordinal ?? index + 1;
}

// Turn the model's inline citation markers into separate links. ReactMarkdown
// renders adjacent links without a separator, so "[5][9]" used to look like
// "59"; keeping one link per ordinal lets the stylesheet draw distinct chips.
// A marker that names no known citation is left as written.
export function linkCitationMarkers(text, citations) {
  const source = String(text ?? "");
  const list = Array.isArray(citations) ? citations : [];
  const known = new Set(list.map((citation, index) => citationOrdinal(citation, index)));
  if (known.size === 0) return source;
  return source.replace(/\[(\d+(?:\s*[,，、;；]\s*\d+)*)\]/g, (marker, group) => {
    const numbers = group.split(/\s*[,，、;；]\s*/).map(Number);
    const linked = numbers.map((number) => known.has(number) ? `[${number}](#citation-${number})` : null);
    if (linked.every((value) => value === null)) return marker;
    return numbers.map((number, index) => linked[index] ?? `[${number}]`).join("");
  });
}

// Citation protocol v2 (server-issued nodes).  Under v2 the answer text is shown as written: a hand-typed
// [n] is plain text, never a link.  The citation components are the issued nodes only, in issue order, each
// resolved to this answer's own citation for that ordinal.  Under v1 nothing changes.
export function renderAnswerText(text, citations, protocol) {
  return protocol === "v2" ? String(text ?? "") : linkCitationMarkers(text, citations);
}

export function citationsToShow(protocol, citations, nodes) {
  const list = Array.isArray(citations) ? citations : [];
  if (protocol !== "v2") return list;
  const shown = [];
  const seen = new Set();
  for (const node of Array.isArray(nodes) ? nodes : []) {
    const ref = String(node?.source_ref ?? "");
    if (!ref || seen.has(ref)) continue;
    const index = list.findIndex((citation, i) => String(citationOrdinal(citation, i)) === ref);
    if (index === -1) continue;
    seen.add(ref);
    shown.push(list[index]);
  }
  return shown;
}
