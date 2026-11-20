import assert from "node:assert/strict";
import test from "node:test";
import { librarySymbol, usableFocus } from "../src/material-focus.mjs";

test("全部股票 sends no symbol; 当前股票 sends the current one", () => {
  assert.equal(librarySymbol("all", "AAPL"), "");
  assert.equal(librarySymbol("current", "AAPL"), "AAPL");
});

test("a focus without an analysis still locates the material", () => {
  assert.deepEqual(usableFocus({ symbol: "AAPL", source_type: "uploaded_media", source_id: "x1" }, "AAPL"),
    { symbol: "AAPL", source_type: "uploaded_media", source_id: "x1", analysis_id: null });
  assert.equal(usableFocus({ symbol: "MSFT", source_type: "uploaded_media", source_id: "x1" }, "AAPL"), null);
  assert.equal(usableFocus({ symbol: "AAPL", source_type: "web", source_id: "x1" }, "AAPL"), null);
});
