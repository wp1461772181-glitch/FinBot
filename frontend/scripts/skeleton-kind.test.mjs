import assert from "node:assert/strict";
import test from "node:test";
import { skeletonKind } from "../src/skeleton-kind.mjs";

test("a page's skeleton has the shape of the page it stands for", () => {
  const cases = {
    "/chat": "messages", "/chat/news-1": "messages", "/chat/c/abc": "messages", "/chat/news-1/settings": "messages",
    "/chat/history": "rows",
    "/research": "cards", "/research/c/AAPL?tab=forecasts": "cards", "/research/scores": "cards", "/research/monitor": "cards",
    "/research/materials?symbol=AAPL": "table", "/research/forecasts": "table", "/research/replay": "table",
    "/portfolio": "table", "/routines?tab=runs": "rows", "/assistant/skills": "rows", "/settings/models": "cards", "/nowhere": "rows",
  };
  for (const [path, kind] of Object.entries(cases)) assert.equal(skeletonKind(path), kind, path);
});
