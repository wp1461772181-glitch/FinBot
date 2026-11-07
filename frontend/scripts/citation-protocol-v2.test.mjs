import assert from "node:assert/strict";
import test from "node:test";
import { citationsToShow, renderAnswerText } from "../src/chat-citations.mjs";

const citations = [{ ordinal: 1, title: "price" }, { ordinal: 2, title: "filing" }, { ordinal: 3, title: "news" }];

test("v2 shows only the issued nodes' sources, in issue order, once each", () => {
  const nodes = [{ source_ref: "2" }, { source_ref: "2" }, { source_ref: "9" }, { source_ref: "1" }];
  assert.deepEqual(citationsToShow("v2", citations, nodes).map((c) => c.ordinal), [2, 1]);
});

test("v2 with no nodes shows no citation components, even when the turn held sources", () => {
  assert.deepEqual(citationsToShow("v2", citations, []), []);
  assert.deepEqual(citationsToShow("v2", citations, undefined), []);
});

test("v1 is unchanged: every citation shows and markers link", () => {
  assert.equal(citationsToShow(undefined, citations, []).length, 3);
  assert.equal(renderAnswerText("AMD 为 100 [1]。", citations, undefined), "AMD 为 100 [1](#citation-1)。");
});

test("v2 never turns a hand-typed marker into a link", () => {
  assert.equal(renderAnswerText("AMD 为 100 [1]。", citations, "v2"), "AMD 为 100 [1]。");
});
