// Which trace of thinking and which caret a persona gets (design 6.6).  Pure.  Apart from signature.mjs (which the chat line needs for the closing line)
// because only the lazy parts that dress a line for its bot (PersonaAttrs, the rehearsal, the sample page) ask which signature a persona wears:
// the chat page's own code does not carry this table.  signature.mjs re-exports all of it.

/** The six traces of thinking (the process bar's first cell), by name.  Each is one `@keyframes` family in bots-signature.css. */
export const TRACES = ["candles", "streaks", "steps", "arc", "lines", "drift", "orbit"];

/** The five carets.  The lead and the generalist share the plain bar (the design lists five). */
export const CURSORS = ["bar", "slant", "underline", "hairline", "bar-block"];

/**
 * Persona -> { trace, cursor }.  The tracker's variant decides: speed-lines (the quick one) streaks, halo (the calm one) arc.  The standard
 * tracker (reticle) keeps its family's slanted caret and a drift: the same three short lines as the quick one's streaks, at a constant
 * speed and evenly spaced, so it reads as that bot's even-tempered sibling.
 */
export function signatureOf(persona) {
  const archetype = persona?.archetype, variant = persona?.auraVariant;
  if (archetype === "lead") return { trace: "candles", cursor: "bar" };
  if (archetype === "sentinel") return { trace: "steps", cursor: "underline" };
  if (archetype === "reader") return { trace: "lines", cursor: "bar-block" };
  if (archetype === "tracker") {
    if (variant === "speed-lines") return { trace: "streaks", cursor: "slant" };
    if (variant === "halo") return { trace: "arc", cursor: "hairline" };
    return { trace: "drift", cursor: "slant" };
  }
  return { trace: "orbit", cursor: "bar" };
}
