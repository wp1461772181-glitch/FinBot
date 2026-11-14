// Fixed, obviously fake identifiers shared by the fixtures and the page list.
export const BOT = {
  finbot: "b0000000-0000-4000-8000-000000000001",
  newsbot: "b0000000-0000-4000-8000-000000000002",
  applebot: "b0000000-0000-4000-8000-000000000003",
  reportbot: "b0000000-0000-4000-8000-000000000004",
  teslabot: "b0000000-0000-4000-8000-000000000005",
};
export const CONVERSATION = {
  finbot: "c0000000-0000-4000-8000-000000000001",
  newsbot: "c0000000-0000-4000-8000-000000000002",
  applebot: "c0000000-0000-4000-8000-000000000003",
  reportbot: "c0000000-0000-4000-8000-000000000004",
  teslabot: "c0000000-0000-4000-8000-000000000005",
  older: "c0000000-0000-4000-8000-000000000011",
};
// Forecast roots (one per formal forecast) and their versions.
export const ROOT = { aapl: "f0000000-0000-4000-8000-000000000001", tsla: "f0000000-0000-4000-8000-000000000002" };
export const VERSION = {
  aapl1: "f1000000-0000-4000-8000-000000000001", aapl2: "f1000000-0000-4000-8000-000000000002", aapl3: "f1000000-0000-4000-8000-000000000003",
  tsla1: "f1000000-0000-4000-8000-000000000011",
};
export const JUDGMENT = { aapl: "e0000000-0000-4000-8000-000000000001", nvda: "e0000000-0000-4000-8000-000000000002" };
export const WATCHLIST = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "GOOGL", "AMZN"];
// The login code the fake server accepts (an invented one) and the marker that makes the fake stream hang.
export const LOGIN_CODE = "shots-fixture-login-code";
export const HOLD_MARKER = "[hold-the-answer]";
// P3.1: a message holding ASK_MARKER is answered with a clarification card (the turn waits for the user's pick);
// a message holding HAND_MARKER never reaches the fake API: smoke.mjs feeds that stream by hand (fake-sse.mjs).
export const ASK_MARKER = "[ask-which]";
export const HAND_MARKER = "[hand-fed]";
