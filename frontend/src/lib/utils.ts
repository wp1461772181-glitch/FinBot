import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind-merge has to know the design's own type steps (theme.css: text-caption … text-display).  Unknown, it reads
// `text-small` as a text colour and silently drops the real colour class next to it.
const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: ["caption", "small", "body", "chat", "title-s", "title-m", "title-l", "display"] }] } },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
