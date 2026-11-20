export type BadgeToneKind = "success" | "failure" | "progress" | "neutral";
export declare function statusKind(status: string | null | undefined): BadgeToneKind;
export declare function scheduleSummary(task: Record<string, any>, locale?: string): string;
export declare function taskState(task: Record<string, any>, enabled?: boolean): "finished" | "paused" | null;
export declare function tasksOfBot<T extends { bot_id: string | null }>(tasks: T[] | null | undefined, botId: string): T[];
export declare function runsOfBot<T extends { task_id: string }>(runs: T[] | null | undefined, tasks: Array<{ id: string; bot_id: string | null }> | null | undefined, botId: string): T[];
export declare function botFilter(value: string | null | undefined, bots: Array<{ id: string }> | null | undefined): string;
