import test from "node:test";
import assert from "node:assert/strict";
import { CHANNEL_OPTIONS, CHANNEL_STATE_TEXT, deliveryRow, deliveryStatusText, optionForPrefs, prefsForOption, rawOrderText, channelState } from "../src/channel-prefs.mjs";

test("the three options map to prefs and back", () => {
  assert.deepEqual(CHANNEL_OPTIONS.map((o) => o.id), ["telegram-only", "wechat-first", "both"]);
  assert.deepEqual(prefsForOption("telegram-only"), { channels: ["telegram"], mode: "first" });
  assert.deepEqual(prefsForOption("wechat-first"), { channels: ["wechat", "telegram"], mode: "first" });
  assert.deepEqual(prefsForOption("both"), { channels: ["wechat", "telegram"], mode: "all" });
  for (const o of CHANNEL_OPTIONS) assert.equal(optionForPrefs(prefsForOption(o.id)), o.id);
  assert.equal(prefsForOption("nope"), null);
});

test("prefs that match no option select nothing and show their raw order", () => {
  const odd = { channels: ["telegram", "wechat"], mode: "first" };
  assert.equal(optionForPrefs(odd), "");
  assert.equal(optionForPrefs({ channels: ["wechat"], mode: "first" }), "");
  assert.equal(optionForPrefs(null), "");
  assert.equal(rawOrderText(odd), "Telegram → 微信 · first");
  assert.equal(rawOrderText({ channels: ["wechat"], mode: "all" }), "微信 · all");
});

test("a returned prefs object is not shared with the option table", () => {
  prefsForOption("both").channels.push("x");
  assert.deepEqual(prefsForOption("both").channels, ["wechat", "telegram"]);
});

const UP = { wechat: true, telegram: true }, NO_WECHAT = { wechat: false, telegram: true }, NO_TELEGRAM = { wechat: true, telegram: false }, NONE = { wechat: false, telegram: false };

test("channelState: every option against every availability", () => {
  const table = {
    "telegram-only": [UP, NO_WECHAT, NO_TELEGRAM, NONE].map((a) => [a, ["", "", "none", "none"][[UP, NO_WECHAT, NO_TELEGRAM, NONE].indexOf(a)]]),
    "wechat-first": [[UP, ""], [NO_WECHAT, "wechat-falls-back"], [NO_TELEGRAM, "no-backup"], [NONE, "none"]],
    both: [[UP, ""], [NO_WECHAT, "only-telegram"], [NO_TELEGRAM, "only-wechat"], [NONE, "none"]],
  };
  for (const [id, cases] of Object.entries(table)) for (const [available, want] of cases) assert.equal(channelState(id, available), want, `${id} ${JSON.stringify(available)}`);
  assert.equal(channelState("", NONE), "");
  assert.equal(channelState("both", null), "");
  assert.equal(channelState("both", undefined), "");
});

test("channelState sentences", () => {
  assert.equal(CHANNEL_STATE_TEXT.none, "所选渠道都没有连接，主动消息现在发不出去。");
  assert.equal(CHANNEL_STATE_TEXT["wechat-falls-back"], "微信还没有连接，消息会改发 Telegram。");
  assert.equal(CHANNEL_STATE_TEXT["no-backup"], "Telegram 还没有绑定，微信发不出去时没有备用。");
  assert.equal(CHANNEL_STATE_TEXT["only-telegram"], "微信还没有连接，只会发到 Telegram。");
  assert.equal(CHANNEL_STATE_TEXT["only-wechat"], "Telegram 还没有绑定，只会发到微信。");
});

const row = (over) => ({ id: 1, channel: "wechat", status: "sent", failure: null, created_at: "2026-11-24T01:02:03Z", acked_at: null, text: "第一行\n第二行", ...over });

test("a delivery row's status text", () => {
  assert.equal(deliveryStatusText(row({ status: "sent" })), "已发出");
  const now = Date.parse("2026-11-24T01:10:03Z");
  assert.equal(deliveryStatusText(row({ status: "pending", created_at: "2026-11-24T01:09:30Z" }), undefined, now), "排队中");
  assert.equal(deliveryStatusText(row({ status: "pending", created_at: "2026-11-24T01:09:03Z" }), undefined, now), "排队中");
  assert.equal(deliveryStatusText(row({ status: "pending" }), undefined, now), "排队中（已等 8 分钟）");
  assert.equal(deliveryStatusText(row({ status: "pending" }), (s) => `<${s}>`, now), "<排队中（已等 {n} 分钟）>".replace("{n}", "8"));
  assert.equal(deliveryStatusText(row({ status: "pending", created_at: "bad" }), undefined, now), "排队中");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "send_failed" })), "发送失败（发送出错）");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "expired" })), "发送失败（超时没发）");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "not_connected" })), "发送失败");
  assert.equal(deliveryStatusText(row({ status: "sent", failure: "partial" })), "只发出了一部分");
  assert.equal(deliveryStatusText(row({ status: "sent", failure: "partial" }), (s) => `<${s}>`), "<只发出了一部分>");
  assert.equal(deliveryStatusText(row({ status: "sent", failure: null })), "已发出");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: null })), "发送失败");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "weird" })), "发送失败");
  const upper = (s) => `<${s}>`;
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "expired" }), upper), "<发送失败（{reason}）>".replace("{reason}", "<超时没发>"));
});

test("a delivery row keeps the channel name, the ack and the first line of the text", () => {
  const r = deliveryRow(row({ acked_at: "2026-11-24T02:00:00Z" }));
  assert.equal(r.channelLabel, "微信");
  assert.equal(r.acked, true);
  assert.equal(r.firstLine, "第一行");
  assert.equal(deliveryRow(row({ channel: "telegram" })).channelLabel, "Telegram");
  assert.equal(deliveryRow(row()).acked, false);
  assert.equal(deliveryRow(row({ status: "sent", sent_at: "2026-11-24T01:05:00Z" })).time, "2026-11-24T01:05:00Z");
  assert.equal(deliveryRow(row({ status: "sent", sent_at: null })).time, "2026-11-24T01:02:03Z");
  assert.equal(deliveryRow(row({ status: "failed", sent_at: "2026-11-24T01:05:00Z" })).time, "2026-11-24T01:02:03Z");
  assert.equal(deliveryRow(row({ status: "pending" })).time, "2026-11-24T01:02:03Z");
  assert.equal(deliveryRow(row({ text: "\n\n  开头空行  \n后面" })).firstLine, "开头空行");
  assert.equal(deliveryRow(row({ text: null })).firstLine, "");
});
