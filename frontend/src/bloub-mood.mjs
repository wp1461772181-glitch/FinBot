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

// One set of faces per archetype (design 6.3 "表情" column, 6.5 each bot's character).  Every set covers every phase the director
// shows: listen (composer focused), waiting (sent, nothing back), tool, verify, answer, hold (the ball is in your court).  Same rules as
// above: ids of the catalogue, restrained, never CALM, no face twice in a row when the sequence loops.  `MOODS` stays the lead's set.
export const MOODS_BY_ARCHETYPE = {
  lead: { ...MOODS, listen: ["attentif"], verify: ["mefiant"], hold: ["attentif"] },
  tracker: { waiting: ["attentif", "curieux"], tool: ["curieux", "attentif"], verify: ["mefiant"], answer: ["fier", "curieux"], listen: ["attentif"], hold: ["attentif"] },
  sentinel: { waiting: ["attentif", "mefiant"], tool: ["attentif", "surpris", "mefiant"], verify: ["mefiant"], answer: ["curieux", "attentif"], listen: ["attentif"], hold: ["attentif"] },
  reader: { waiting: ["attentif", "curieux"], tool: ["mefiant", "attentif"], verify: ["mefiant", "attentif"], answer: ["curieux", "fier"], listen: ["attentif"], hold: ["attentif"] },
  generalist: { ...MOODS, listen: ["attentif"], verify: ["mefiant"], hold: ["attentif"] }
};

/** Seconds a face is held, and seconds the engine takes to morph into the next (HOLD >= 2 x MOOD_MORPH: it settles before it moves). */
export const HOLD = 1.8;
export const MOOD_MORPH = 0.8;

/** The face for `phase`, `elapsed` seconds after the phase began. Unknown phase: calm.  `archetype` picks that archetype's set
 * (unknown or missing: the lead's, i.e. `MOODS`). */
export function moodAt(phase, elapsed, archetype) {
  const seq = (MOODS_BY_ARCHETYPE[archetype] ?? MOODS)[phase];
  if (!seq) return CALM;
  return seq[Math.floor(Math.max(0, elapsed) / HOLD) % seq.length];
}
