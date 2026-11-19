// The skill editor as plain data (P8.1): what the drawer opens with, and the request each save makes (the old page's, key for key).

export const NAME_MAX = 40;
export const DESCRIPTION_MAX = 120;
export const BODY_MAX = 6000;
export const TEMPLATE_MAX = 2000;
export const IMPORT_MAX = 20000;
export const LEVEL_LABELS = { read: "只读", reversible: "可撤销", costly: "耗费较大", write: "写操作" };
const WRITE_LEVELS = new Set(["reversible", "costly", "write"]);
/** A tool that changes something (it can be undone, costs a lot, or writes) is marked, and the skill's use of it still needs a confirmation card. */
export const isWriteLevel = (level) => WRITE_LEVELS.has(level);

export const blankEditor = () => ({ id: null, name: "", description: "", body: "", template: "", tools: [], draft: false });
export const editorOf = (skill) => ({ id: skill.id, name: skill.name, description: skill.description, body: skill.body, template: skill.output_template ?? "", tools: [...skill.allowed_tools], draft: skill.status === "draft" });

/** The fields every save sends: the name and the one-line description without their ends, the steps as written, the tools in the order they were ticked, the template or null. */
export const inputOf = (editor) => ({ name: editor.name.trim(), description: editor.description.trim(), body: editor.body, allowed_tools: editor.tools, output_template: editor.template.trim() || null });

/** The save: a new skill is created enabled; an existing one is updated (no `enabled`); a draft that is saved says so with `save_draft`. */
export function saveOf(editor) {
  const input = inputOf(editor);
  if (!editor.id) return { create: true, body: { ...input, enabled: true } };
  return { create: false, id: editor.id, body: editor.draft ? { ...input, save_draft: true } : input };
}

/** A tool ticked or unticked: ticking appends (the order is the order of the ticks), unticking removes. */
export const toggleTool = (tools, name, on) => (on ? (tools.includes(name) ? tools : [...tools, name]) : tools.filter((n) => n !== name));

/** What an address /assistant/skills/<id> asks for once the list is in: that skill's editor, "missing", or nothing (a built-in has no editor; an address without an id has no ask). */
export function linkTarget(skills, skillId) {
  if (!skillId) return { kind: "none" };
  const skill = skills.find((s) => s.id === skillId);
  if (!skill) return { kind: "missing" };
  return skill.builtin ? { kind: "builtin" } : { kind: "editor", skill };
}

/** Only an active skill has the on / off switch (a draft is not in use yet). */
export const hasSwitch = (skill) => skill.status === "active";
/** A built-in has no editor and no delete; the owner's own, imported and drafted skills have both. */
export const isEditable = (skill) => !skill.builtin;
/** What a card's file is called when it is exported. */
export const exportName = (skill) => `${skill.name}.md`;
