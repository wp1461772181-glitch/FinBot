// Work-phase faces: the expression layer that sits on top of the body state while a turn runs. Pure (no engine, no clock):
// the director calls moodAt with the time spent in the current phase. Every bot rests on CALM; only work changes the face.
//
// Sequences stay semantically adjacent and restrained (focus -> curiosity -> doubt ...); comic or strong faces
// (hilare, colere, excite ...) belong to clicks and never appear here. Ids are the engine's ExpressionId.
export const CALM = "neutre";
export const MOODS = {
  waiting: ["attentif", "curieux"],            // waiting for the first token: attentive, then curious
  tool: ["attentif", "mefiant", "curieux"],    // running a tool: focus, a checking squint, curiosity
  answer: ["curieux", "fier"]                  // generating the answer: thinking, then "got it"
};
/** Seconds a face is held, and seconds the engine takes to morph into the next (HOLD >= 2 x MOOD_MORPH: it settles before it moves). */
export const HOLD = 1.8;
export const MOOD_MORPH = 0.8;

/** The face for `phase`, `elapsed` seconds after the phase began. Unknown phase: calm. */
export function moodAt(phase, elapsed) {
  const seq = MOODS[phase];
  if (!seq) return CALM;
  return seq[Math.floor(Math.max(0, elapsed) / HOLD) % seq.length];
}
