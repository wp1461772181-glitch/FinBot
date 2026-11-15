// The auras by name.  Every aura variant of bot-persona.AURA_VARIANTS is drawn by one function of one file; the shape of a unit is a
// parameter of that function (the second argument).  `auraFor(variant)` returns `input -> primitives` (unknown names fall back to the
// archetype-less generalist's, so a bad override can never leave a bot without a complete aura).
//   archetype   variant        file               form argument
//   lead        ticks          ticks.mjs          "ticks"
//               gauge          ticks.mjs          "gauge"
//               pips           ticks.mjs          "pips"
//   tracker     speed-lines    speed-lines.mjs    -
//               halo           halo.mjs           -
//               reticle        reticle.mjs        -
//   sentinel    ticker         ticker.mjs         "ticker"
//               morse          ticker.mjs         "morse"
//               beacon         ticker.mjs         "beacon"
//   reader      page-lines     page-lines.mjs     "page-lines"
//               margin-ticks   page-lines.mjs     "margin-ticks"
//               underline      page-lines.mjs     "underline"
//   generalist  orbit-dots     orbit-dots.mjs     "orbit-dots"
//               twin-dots      orbit-dots.mjs     "twin-dots"
//               trio           orbit-dots.mjs     "trio"
import { ticks } from "./ticks.mjs";
import { speedLines } from "./speed-lines.mjs";
import { ticker } from "./ticker.mjs";
import { halo } from "./halo.mjs";
import { pageLines } from "./page-lines.mjs";
import { orbitDots } from "./orbit-dots.mjs";
import { reticle } from "./reticle.mjs";

const make = (fn, form) => input => fn(input, form);
/** variant name -> aura function (every name in bot-persona.AURA_VARIANTS). */
export const AURAS = {
  ticks: make(ticks, "ticks"), gauge: make(ticks, "gauge"), pips: make(ticks, "pips"),
  "speed-lines": speedLines, halo, reticle,
  ticker: make(ticker, "ticker"), morse: make(ticker, "morse"), beacon: make(ticker, "beacon"),
  "page-lines": make(pageLines, "page-lines"), "margin-ticks": make(pageLines, "margin-ticks"), underline: make(pageLines, "underline"),
  "orbit-dots": make(orbitDots, "orbit-dots"), "twin-dots": make(orbitDots, "twin-dots"), trio: make(orbitDots, "trio")
};
export const auraFor = variant => AURAS[variant] ?? AURAS["orbit-dots"];
export { PHASES, TONES, endLength } from "./shared.mjs";
