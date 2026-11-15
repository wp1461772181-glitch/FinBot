// What a typed or pasted text becomes in a tag input (components/TagInput.tsx), pure so a node test can hold it.
export const SPLIT = /[\s,，、;；]+/;

/** The items to add (normalised, new, valid, within the limit), those refused as invalid (as typed), and whether the limit cut some. */
export function readTags(text, current, { normalize = (raw) => raw.trim(), validate = () => true, max } = {}) {
  const add = [], invalid = [];
  let cut = false;
  for (const raw of String(text ?? "").split(SPLIT)) {
    const item = normalize(raw);
    if (!item) continue;
    if (current.includes(item) || add.includes(item)) continue;
    if (!validate(item)) { invalid.push(raw.trim()); continue; }
    if (max !== undefined && current.length + add.length >= max) { cut = true; continue; }
    add.push(item);
  }
  return { add, invalid, cut };
}
