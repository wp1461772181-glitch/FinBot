// The full judgement of the level of animation (design 6.9 P9 / P10), pure.  Priority: the system's reduced-motion setting (always "off", nothing in the
// page can ask for more) > the level the reader chose in this browser > a judgement of the device > a mid-visit drop after slow frames > "full".
// Not part of the first screen: start-up (motion-level.mjs) settles the first three of these from storage and the system setting alone; the avatar's
// and the settings page's chunks complete the judgement with the device and the drop (motion-control.mjs).
import { LEVELS } from "./motion-store.mjs";

/** A device with this many cores or fewer AND this much memory (GB) or less starts on "lite"; data-saver mode alone does it too.  Memory
 * that is not known (Safari and Firefox do not report it) does not count as low: a plain laptop must not start one layer short. */
export const LOW_CORES = 4;
export const LOW_MEMORY_GB = 4;
const REDUCED = "(prefers-reduced-motion: reduce)";
const known = value => typeof value === "number" && value > 0;

export const isLowEnd = ({ cores, memoryGB, saveData } = {}) => saveData === true || (known(cores) && cores <= LOW_CORES && known(memoryGB) && memoryGB <= LOW_MEMORY_GB);

/** `{ level, source }`; source: "system" | "user" | "auto-device" | "auto-runtime" | "default".  `runtimeDowngraded` only matters when nothing above it decided. */
export function resolveMotionLevel({ stored, prefersReduced, hardware, runtimeDowngraded } = {}) {
  const [level, source] = prefersReduced ? ["off", "system"] : LEVELS.includes(stored) ? [stored, "user"]
    : isLowEnd(hardware) ? ["lite", "auto-device"] : runtimeDowngraded ? ["lite", "auto-runtime"] : ["full", "default"];
  return { level, source };
}

export function readHardware(nav = globalThis.navigator) {
  return { cores: nav?.hardwareConcurrency, memoryGB: nav?.deviceMemory, saveData: nav?.connection?.saveData };
}
