// Pure helpers of the new-bot dialog (P5.2): what a create sends, and the stand-in bot whose personality the preview shows.
import { newBotFields } from "./bot-form-items.mjs";
import { DEFAULT_AVATAR } from "./orb.mjs";

/** The id of the preview's stand-in bot: not a real one, only a stable seed for what is derived from an id. */
export const PREVIEW_BOT_ID = "new-bot-preview";

/**
 * The request body of a create.  It is what the old dialog sent for the same input (newBotFields: the trimmed name and nothing else unless a
 * template was picked, a template only pre-fills what was left blank), plus the robot avatar and the look that is on screen.
 */
export function createFields(name, template, tools, look) {
  return { ...newBotFields(name, template, tools), avatar: DEFAULT_AVATAR, look };
}

/** The name a create would use (the typed one, else the template's); empty means the button waits. */
export function createName(name, template, tools) { return newBotFields(name, template, tools).name; }

/**
 * The bot the preview stands in for: nothing a rule of the personality (bot-persona 6.4) reads except the template, so the preview shows what the
 * bot will be.  The name is fixed on purpose: a typed name must not change the personality (a few names are pinned presets), and the id is a seed.
 */
export function previewBot(template, name = "新 bot") {
  return { id: PREVIEW_BOT_ID, name, template: template?.id ?? "blank", is_default: false, default_company: null, focus: { companies: [], theme: null } };
}
