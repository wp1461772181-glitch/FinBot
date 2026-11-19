import assert from "node:assert/strict";
import test from "node:test";
import { APPROVAL_TTL_MS as CARD } from "../src/approval-card.mjs";
import { APPROVAL_TTL_MS as SIGNALS } from "../src/approval-ttl.mjs";

// The card's logic and the avatar's signals each hold the ten minutes of a write confirmation (see the note in approval-card.mjs); they must stay one number.
test("the card and the avatar's signals count the same ten minutes", () => {
  assert.equal(CARD, SIGNALS);
  assert.equal(CARD, 10 * 60 * 1000);
});
