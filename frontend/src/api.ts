// Re-export hub for the request layer.  The functions live in src/api/<domain>.ts.  Code on the first-screen path
// imports from those files directly, because a bundler keeps every module a re-export hub reaches in the hub's own chunk;
// lazy pages may keep importing from here.  Keep this file free of declarations and top-level statements.
export { configuredApiBaseUrl, ApiError, getChatMode, setChatMode } from "./api/base";
export type { ChatMode } from "./api/base";
export * from "./api/bots";
export * from "./api/bots-admin";
export * from "./api/catalog-admin";
export * from "./api/citation";
export * from "./api/conversations";
export * from "./api/evidence-uploads";
export * from "./api/forecast-v2";
export * from "./api/inbox";
export * from "./api/inbox-actions";
export * from "./api/integrations";
export * from "./api/knowledge-docs";
export * from "./api/market-data";
export * from "./api/material-library";
export * from "./api/memory";
export * from "./api/news-sources";
export * from "./api/owner";
export * from "./api/portfolio-ledger";
export * from "./api/prices";
export * from "./api/queue";
export * from "./api/skills-admin";
export * from "./api/skills-core";
export * from "./api/tasks";
