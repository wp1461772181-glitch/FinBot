export type UpdownChoice = "green-up" | "red-up";
export const UPDOWN_KEY: string;
export const UPDOWNS: UpdownChoice[];
export const DEFAULT_UPDOWN: UpdownChoice;
export function storedUpdown(storage?: Storage): UpdownChoice;
export function applyUpdown(choice: UpdownChoice, root?: HTMLElement): UpdownChoice;
export function saveUpdown(choice: UpdownChoice, storage?: Storage): UpdownChoice;
