import test from "node:test";
import assert from "node:assert/strict";
import { CHANNEL_OPTIONS, deliveryRow, deliveryStatusText, optionForPrefs, prefsForOption, rawOrderText, fallbackWarning } from "../src/channel-prefs.mjs";

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

test("the fallback warning shows only when the first channel is down and another channel exists", () => {
  assert.equal(fallbackWarning("wechat-first", { wechat: false, telegram: true }), true);
  assert.equal(fallbackWarning("both", { wechat: false, telegram: true }), true);
  assert.equal(fallbackWarning("wechat-first", { wechat: true, telegram: false }), false);
  assert.equal(fallbackWarning("telegram-only", { wechat: false, telegram: false }), false);
  assert.equal(fallbackWarning("", { wechat: false, telegram: true }), false);
  assert.equal(fallbackWarning("wechat-first", null), false);
});

const row = (over) => ({ id: 1, channel: "wechat", status: "sent", failure: null, created_at: "2026-11-24T01:02:03Z", acked_at: null, text: "第一行\n第二行", ...over });

test("a delivery row's status text", () => {
  assert.equal(deliveryStatusText(row({ status: "sent" })), "已发出");
  assert.equal(deliveryStatusText(row({ status: "pending" })), "排队中");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "send_failed" })), "发送失败（发送出错）");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "expired" })), "发送失败（超时没发）");
  assert.equal(deliveryStatusText(row({ status: "failed", failure: "not_connected" })), "发送失败（渠道未连接）");
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
  assert.equal(deliveryRow(row({ text: "\n\n  开头空行  \n后面" })).firstLine, "开头空行");
  assert.equal(deliveryRow(row({ text: null })).firstLine, "");
});
