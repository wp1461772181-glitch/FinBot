import test from "node:test";
import assert from "node:assert/strict";
import { FOLLOW_SLACK, bottomScrollTop, distanceFromBottom, isFollowing, keepPositionAfterPrepend, showJumpToBottom } from "../src/chat-scroll.mjs";

const box = (scrollHeight, scrollTop, clientHeight = 500) => ({ scrollHeight, scrollTop, clientHeight });

test("at the bottom the page follows and offers no jump", () => {
  assert.equal(distanceFromBottom(box(2000, 1500)), 0);
  assert.equal(isFollowing(box(2000, 1500)), true);
  assert.equal(showJumpToBottom(box(2000, 1500)), false);
});

test("within the slack still counts as the bottom (a growing last line does not lose the follow)", () => {
  assert.equal(isFollowing(box(2000, 1500 - (FOLLOW_SLACK - 1))), true);
  assert.equal(isFollowing(box(2000, 1500 - FOLLOW_SLACK)), false);
});

test("one scroll up stops following and shows 回到底部; scrolling back down restores both", () => {
  const up = box(2000, 900);
  assert.equal(isFollowing(up), false);
  assert.equal(showJumpToBottom(up), true);
  const back = box(2000, 1490);
  assert.equal(isFollowing(back), true);
  assert.equal(showJumpToBottom(back), false);
});

test("a thread shorter than the box is at its bottom", () => {
  assert.equal(isFollowing(box(300, 0)), true);
  assert.equal(showJumpToBottom(box(300, 0)), false);
  assert.equal(bottomScrollTop(box(300, 0)), 0);
});

test("the bottom position is the content height minus the box", () => {
  assert.equal(bottomScrollTop(box(2000, 0)), 1500);
});

test("older messages put above keep the line the reader was on", () => {
  assert.equal(keepPositionAfterPrepend({ scrollHeight: 1000, scrollTop: 12 }, 1800), 812);
});
