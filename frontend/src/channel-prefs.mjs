// Where proactive messages go (settings > notifications): three plain choices over the server's prefs {channels, mode}, and one row of the delivery list.
// Source phrases are Chinese; the page passes each through t().

const CHANNEL_NAMES = { telegram: "Telegram", wechat: "微信" };

/** The three choices.  `label` and `hint` are source phrases. */
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

/** True when the option's first channel is not available and another channel is there to take the message (the page then says 「微信还没有连接，消息会改发 Telegram。」). */
export function fallbackWarning(optionId, available) {
  const option = CHANNEL_OPTIONS.find((o) => o.id === optionId);
  if (!option || !available || option.channels.length < 2) return false;
  return available[option.channels[0]] === false;
}

const FAILURE_REASONS = { send_failed: "发送出错", expired: "超时没发", not_connected: "渠道未连接" };

/** 已发出 / 发送失败（原因） / 排队中.  `t` translates each phrase; the reason is left out when the server gave none this page knows. */
export function deliveryStatusText(item, t = (text) => text) {
  if (item?.status === "sent") return t("已发出");
  if (item?.status === "failed") {
    const reason = Object.hasOwn(FAILURE_REASONS, item.failure ?? "") ? FAILURE_REASONS[item.failure] : "";
    return reason ? t("发送失败（{reason}）").replace("{reason}", t(reason)) : t("发送失败");
  }
  return t("排队中");
}

/** What a delivery line shows besides its time and status: the channel's name, whether the owner came back after it, the first line of the text. */
export function deliveryRow(item) {
  const firstLine = typeof item?.text === "string" ? (item.text.split("\n").map((line) => line.trim()).find((line) => line !== "") ?? "") : "";
  return { channelLabel: CHANNEL_NAMES[item?.channel] ?? String(item?.channel ?? ""), acked: Boolean(item?.acked_at), firstLine };
}
