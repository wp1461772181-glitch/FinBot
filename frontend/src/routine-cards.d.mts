export type ConfirmEntry = {
  key: string; kind: "proposal" | "suggestion"; id: string; botId: string | null; title: string; detail: string; targets: Array<Record<string, string>>; taskName: string;
  createdAt: string | null; expiresAt: string | null; conversationId: string | null; state: string | null; token: string | null; phase: "live" | "expired" | "done";
};
export type EntryChoice = { value: string; label: string; disabled?: boolean };
export declare function confirmEntries(proposals: unknown, confirms: unknown): ConfirmEntry[];
export declare function liveCount(entries: ConfirmEntry[]): number;
export declare function entryCard(entry: ConfirmEntry): {
  card: { request_id: string; reason: string; question?: string; display: { title?: string; targets: Array<Record<string, string>>; agent_suggestion?: boolean }; choices: EntryChoice[] };
  layout: { layout: "confirm"; primary: EntryChoice | null; secondary: EntryChoice | null; more: EntryChoice[]; list: EntryChoice[] };
};
