// Where proactive messages go (settings > notifications): three plain choices over the server's prefs {channels, mode}, and one row of the delivery list.
// Source phrases are Chinese; the page passes each through t().

const CHANNEL_NAMES = { telegram: "Telegram", wechat: "微信" };

/** The three choices.  `label` is a source phrase. */
export const CHANNEL_OPTIONS = [
  { id: "telegram-only", label: "只发 Telegram", channels: ["telegram"], mode: "first" },
  { id: "wechat-first", label: "先发微信，发不出去再发 Telegram", channels: ["wechat", "telegram"], mode: "first" },
  { id: "both", label: "微信和 Telegram 都发", channels: ["wechat", "telegram"], mode: "all" },
];

const sameChannels = (a, b) => Array.isArray(a) && a.length === b.length && a.every((c, i) => c === b[i]);

/** The id of the option the stored prefs are, or "" when they are none of the three (set through the API, or not read yet). */
export function optionForPrefs(prefs) {
  if (!prefs) return "";
  return CHANNEL_OPTIONS.find((o) => o.mode === prefs.mode && sameChannels(prefs.channels, o.channels))?.id ?? "";
}

/** The prefs an option stands for (a fresh object), or null for an unknown id. */
export function prefsForOption(id) {
  const option = CHANNEL_OPTIONS.find((o) => o.id === id);
  return option ? { channels: [...option.channels], mode: option.mode } : null;
}

/** A stored preference that matches no option, as it is: 「Telegram → 微信 · first」. */
export function rawOrderText(prefs) {
  const names = (Array.isArray(prefs?.channels) ? prefs.channels : []).map((c) => CHANNEL_NAMES[c] ?? String(c));
  return `${names.join(" → ")} · ${prefs?.mode ?? ""}`;
}

/** The sentence the page says under the choice for each state of the chosen option against the channels that are connected. */
export const CHANNEL_STATE_TEXT = {
  none: "所选渠道都没有连接，主动消息现在发不出去。",
  "wechat-falls-back": "微信还没有连接，消息会改发 Telegram。",
  "no-backup": "Telegram 还没有绑定，微信发不出去时没有备用。",
  "only-telegram": "微信还没有连接，只会发到 Telegram。",
  "only-wechat": "Telegram 还没有绑定，只会发到微信。",
};

/** Which of CHANNEL_STATE_TEXT applies to the chosen option, or "" when there is nothing to say (all fine, nothing chosen, or availability not read). */
export function channelState(optionId, available) {
  const option = CHANNEL_OPTIONS.find((o) => o.id === optionId);
  if (!option || !available) return "";
  const down = option.channels.filter((c) => available[c] === false);
  if (down.length === 0) return "";
  if (down.length === option.channels.length) return "none";
  const wechatDown = down[0] === "wechat";
  if (option.mode === "all") return wechatDown ? "only-telegram" : "only-wechat";
  return wechatDown ? "wechat-falls-back" : "no-backup";
}

const FAILURE_REASONS = { send_failed: "发送出错", expired: "超时没发" };

/**
 * 已发出 / 发送失败（原因） / 排队中.  `t` translates each phrase; the reason is left out when the server gave none this page knows.
 * A queued row older than a minute says how long it has waited (`now`: ms or Date, default the present).
 */
export function deliveryStatusText(item, t = (text) => text, now = Date.now()) {
  if (item?.status === "sent") return item.failure === "partial" ? t("只发出了一部分") : t("已发出");
  if (item?.status === "failed") {
    const reason = Object.hasOwn(FAILURE_REASONS, item.failure ?? "") ? FAILURE_REASONS[item.failure] : "";
    return reason ? t("发送失败（{reason}）").replace("{reason}", t(reason)) : t("发送失败");
  }
  const waited = Number(now) - Date.parse(item?.created_at);
  if (waited > 60000) return t("排队中（已等 {n} 分钟）").replace("{n}", String(Math.floor(waited / 60000)));
  return t("排队中");
}

/** What a delivery line shows besides its status: the time (sent time for a sent row, else creation), the channel's name, whether the owner came back after it, the first line of the text. */
export function deliveryRow(item) {
  const firstLine = typeof item?.text === "string" ? (item.text.split("\n").map((line) => line.trim()).find((line) => line !== "") ?? "") : "";
  const time = item?.status === "sent" && item.sent_at ? item.sent_at : item?.created_at;
  return { time, channelLabel: CHANNEL_NAMES[item?.channel] ?? String(item?.channel ?? ""), acked: Boolean(item?.acked_at), firstLine };
}
