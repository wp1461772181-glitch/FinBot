export type ConnectivitySnapshot = { down: boolean; since: number | null; reason: string };
export type ConnectivityOutcome = "down" | "up" | "ignore";
export type ReplayableRead = { input: RequestInfo | URL; init?: RequestInit };
export function classifyOutcome(result?: { error?: unknown; status?: number; contentType?: string | null }): ConnectivityOutcome;
export function createConnectivity(options?: { now?: () => number }): {
  getSnapshot(): ConnectivitySnapshot;
  subscribe(listener: () => void): () => void;
  report(outcome: ConnectivityOutcome, options?: { reason?: string; replay?: ReplayableRead | null }): void;
  lastFailedRead(): ReplayableRead | null;
  retry(run?: (request: ReplayableRead) => Promise<unknown>): Promise<void>;
};
export function watchConnectivity(store: ReturnType<typeof createConnectivity>, options?: { host?: any; isApi?: (url: string) => boolean }): () => void;
