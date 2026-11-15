import assert from "node:assert/strict";
import test from "node:test";
import { agoParts, cardModel, cardStatus, orderAllBots } from "../src/all-bots-items.mjs";
import { botSections } from "../src/bot-items.mjs";

const bot = (id, extra = {}) => ({ id, name: id, hidden: false, pinned: false, is_default: false, group: "", last_at: null, unread: 0, pending: 0, model: null, ...extra });
const ids = list => list.map(b => b.id);

test("the order is the sidebar's, the hidden bots come last in the same order among themselves", () => {
  const bots = [
    bot("quiet"), bot("old", { last_at: "2026-11-01T00:00:00Z" }), bot("fresh", { last_at: "2026-11-13T00:00:00Z" }), bot("pinned", { pinned: true }),
    bot("hid-a", { hidden: true, last_at: "2026-11-02T00:00:00Z" }), bot("hid-b", { hidden: true, last_at: "2026-11-12T00:00:00Z" }), bot("fin", { is_default: true }),
    bot("grouped", { group: "公司", last_at: "2026-11-13T05:00:00Z" }),
  ];
  const sidebar = botSections(bots.filter(b => !b.hidden));
  const expectShown = [sidebar.top, ...sidebar.groups.flatMap(g => g.bots)].map(b => b.id);
  assert.deepEqual(ids(orderAllBots(bots)), [...expectShown, "hid-b", "hid-a"]);
  assert.equal(ids(orderAllBots(bots))[0], "fin");
});

test("a hidden default bot (it can not be, but a record may say so) still leads, and nothing is lost or doubled", () => {
  const bots = [bot("a", { hidden: true }), bot("fin", { is_default: true, hidden: true }), bot("b")];
  const out = ids(orderAllBots(bots));
  assert.deepEqual(out, ["fin", "b", "a"]);
  assert.deepEqual(ids(orderAllBots([])), []); assert.deepEqual(ids(orderAllBots(null)), []);
});

test("agoParts: the unit rises with the age, a missing or unreadable time is null, the first minute is 'now'", () => {
  const now = Date.parse("2026-11-13T02:00:00Z");
  const at = ms => new Date(now - ms).toISOString();
  assert.deepEqual(agoParts(at(10e3), now), { now: true });
  assert.deepEqual(agoParts(new Date(now + 5e3).toISOString(), now), { now: true }, "a clock a little ahead");
  assert.deepEqual(agoParts(at(35 * 60e3), now), { unit: "minute", value: -35 });
  assert.deepEqual(agoParts(at(15 * 3600e3), now), { unit: "hour", value: -15 });
  assert.deepEqual(agoParts(at(25 * 3600e3), now), { unit: "day", value: -1 });
  assert.deepEqual(agoParts(at(45 * 86400e3), now), { unit: "month", value: -1 });
  assert.deepEqual(agoParts(at(400 * 86400e3), now), { unit: "year", value: -1 });
  assert.equal(agoParts(null, now), null); assert.equal(agoParts("not a time", now), null);
});

test("cardStatus follows the sidebar's precedence: answering, then waiting, then unread; the unread count adds a finished background answer", () => {
  const none = { running: [], unseen: [], waiting: [] };
  assert.deepEqual(cardStatus(bot("a"), none), { status: "idle", word: null, count: 0 });
  assert.deepEqual(cardStatus(bot("a", { unread: 2 }), none), { status: "unread", word: null, count: 2 });
  assert.deepEqual(cardStatus(bot("a", { pending: 1, unread: 2 }), none), { status: "waiting", word: "waiting", count: 2 });
  assert.deepEqual(cardStatus(bot("a", { pending: 1 }), { ...none, running: ["bot:a"] }), { status: "answering", word: "running", count: 0 });
  assert.deepEqual(cardStatus(bot("a", { unread: 1 }), { ...none, unseen: ["bot:a"] }), { status: "unread", word: null, count: 2 });
  assert.deepEqual(cardStatus(bot("a", { pending: 0 }), { ...none, waiting: ["bot:a"] }).status, "waiting");
});

test("cardModel: null when the bot has none of its own (the catalog default applies), else the catalog's display name, else the id", () => {
  const catalog = { models: [{ name: "haiku-5.5", display_name: "Haiku 5.5" }, { name: "plain", display_name: "" }] };
  assert.equal(cardModel(bot("a"), catalog), null);
  assert.equal(cardModel(bot("a", { model: "haiku-5.5" }), catalog), "Haiku 5.5");
  assert.equal(cardModel(bot("a", { model: "plain" }), catalog), "plain");
  assert.equal(cardModel(bot("a", { model: "gone" }), catalog), "gone");
  assert.equal(cardModel(bot("a", { model: "gone" }), null), "gone");
});
