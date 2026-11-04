export type ForecastRoute = {
  view: "home" | "forecast" | "judgment" | "monitor";
  rootId?: string;
  versionId?: string;
  reviseSourceId?: string;
  judgmentId?: string;
  symbol?: string;
};
export declare function parseForecastHash(hash: string): ForecastRoute;
export declare function legacyForecastSection(hash: string): "revisions" | "evaluation" | "replay" | null;
export declare function forecastHash(rootId: string, versionId?: string): string;
export declare function reviseHash(rootId: string, sourceId: string): string;
export declare function judgmentHash(judgmentId: string): string;
export declare function forecastHomeHash(symbol?: string): string;
