// The five existing bots' pinned personalities and recommended looks (D6, checked against the box 2026-11-13).  A module of its own because
// bloub-look.resolveLook (first screen: every avatar) needs the recommended look, while the rest of bot-persona.mjs loads on demand.
/**
 * The five existing bots (D6, checked against the box 2026-11-13).  Pinned: they never go through the derivation.  `look` is the
 * recommended silhouette, used only while the bot has no stored look (bloub-look.resolveLook): the four that already have one
 * keep it, TeslaBot gets capsule / rouge.
 */
export const PERSONA_PRESETS = [
  { id: "ecc4d493-1e26-435d-99e9-cb5699ab7cc6", name: "FinBot", archetype: "lead", tempo: 1, easing: "smooth", restGaze: "follow", auraVariant: "ticks", look: { shape: "cercle", color: "encre" } },
  { id: "c20935c6-c9f9-417c-a900-0afd5dcb5566", name: "TeslaBot", archetype: "tracker", tempo: 1.25, easing: "spring", restGaze: "ahead-right", auraVariant: "speed-lines", look: { shape: "capsule", color: "rouge" } },
  { id: "ca3c9be3-97ea-4ce0-a624-ae6bfeb723e9", name: "NewsBot", archetype: "sentinel", tempo: 1.1, easing: "step", restGaze: "scan", auraVariant: "bulletin", look: { shape: "triangle", color: "orange" } },
  { id: "3694c439-f29e-49dd-9875-51b6c8a4f7fd", name: "AppleBot", archetype: "tracker", tempo: 0.9, easing: "smooth", restGaze: "front", auraVariant: "halo", look: { shape: "squircle", color: "creme" } },
  { id: "67441a6d-b24a-4efc-a57c-bb9391313ece", name: "ReportBot", archetype: "reader", tempo: 0.8, easing: "smooth", restGaze: "down", auraVariant: "page-lines", look: { shape: "hexagone", color: "bleu" } }
];

const squash = value => String(value ?? "").replace(/\s+/g, "").toLowerCase();

/** The preset a bot record hits: by id first, then by name (whitespace removed, case ignored).  null for every other bot. */
export function presetFor(bot) {
  if (!bot || typeof bot !== "object") return null;
  const id = typeof bot.id === "string" ? bot.id : "";
  const byId = id && PERSONA_PRESETS.find(p => p.id === id);
  if (byId) return byId;
  const name = squash(bot.name);
  return name ? PERSONA_PRESETS.find(p => squash(p.name) === name) ?? null : null;
}

/** The recommended look of a preset bot (a copy), or null.  Takes `{ id, name }` — either may be missing. */
export function presetLook(bot) {
  const preset = presetFor(bot);
  return preset ? { ...preset.look } : null;
}

