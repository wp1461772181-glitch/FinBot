import assert from "node:assert/strict";
import test from "node:test";
import { appliesText, checkThresholds, plainNum, presetRows, ruleRows, ruleStatus, settingsView, sigmaPair, sigmaWords, thresholdUnit, watchWriteError, yieldsLine } from "../src/watch-rules-view.mjs";

test("a rule's status: the code or the server's words; anything else is active", () => {
  assert.deepEqual(ruleStatus("active"), { kind: "neutral", label: "生效", active: true });
  assert.equal(ruleStatus("expired").label, "已过期");
  assert.equal(ruleStatus("已过期（不再检查）").label, "已过期");
  assert.equal(ruleStatus("done").label, "已完成");
  assert.equal(ruleStatus("已完成（不再检查）").kind, "success");
  assert.equal(ruleStatus("已完成（不再检查）").active, false);
  assert.equal(ruleStatus(undefined).label, "生效");
  assert.equal(ruleStatus("生效中").active, true);
});

test("plain numbers: no trailing zeros, no exponent, empty when not a number", () => {
  assert.equal(plainNum(2), "2");
  assert.equal(plainNum(2.5), "2.5");
  assert.equal(plainNum("1.50"), "1.5");
  assert.equal(plainNum(0.1 + 0.2), "0.3");
  assert.equal(plainNum(null), "");
  assert.equal(plainNum("x"), "");
});

test("the sigma pair reads an array, {low, high}, or the first two numbers of an object", () => {
  assert.deepEqual(sigmaPair([2, 4]), [2, 4]);
  assert.deepEqual(sigmaPair({ low: 1.5, high: 3 }), [1.5, 3]);
  assert.deepEqual(sigmaPair({ remind: 2.5, major: 5 }), [2.5, 5]);
  assert.equal(sigmaPair([2]), null);
  assert.equal(sigmaPair(null), null);
  assert.equal(sigmaPair("2/4"), null);
});

test("the sigma numbers in words, in both languages", () => {
  assert.equal(sigmaWords([2, 4]), "约 2σ 值得提醒，4σ 算重大");
  assert.equal(sigmaWords([1.5, 3], "en-US"), "about 1.5σ is worth a heads-up, 3σ is major");
  assert.equal(sigmaWords(undefined), "");
});

test("settings: three choices in order with their words; unknown sensitivity is standard; short moves only when true", () => {
  const view = settingsView({ sensitivity: "sensitive", short_moves: true, thresholds: { quiet: [2.5, 5], standard: [2, 4], sensitive: [1.5, 3] } });
  assert.deepEqual(view.choices.map(c => c.value), ["quiet", "standard", "sensitive"]);
  assert.deepEqual(view.choices.map(c => c.label), ["安静", "标准", "灵敏"]);
  assert.equal(view.choices[2].words, "约 1.5σ 值得提醒，3σ 算重大");
  assert.equal(view.sensitivity, "sensitive");
  assert.equal(view.shortMoves, true);
  const odd = settingsView({ sensitivity: "loud", short_moves: "yes" });
  assert.equal(odd.sensitivity, "standard");
  assert.equal(odd.shortMoves, false);
  assert.equal(odd.choices[0].words, "");
  assert.equal(settingsView(null).sensitivity, "standard");
});

const levels = (...pairs) => pairs.map(([threshold, level]) => ({ threshold, level }));
const preset = (extra) => ({ key: "concentration", title: "单只占比过高", text: "t", enabled: true, levels: levels([25, "remind"]), editable: true, hard_guarantee: false, applies_to: ["INTC"], yields_on: [], ...extra });

test("preset rows: levels worded, editable ones with a unit can be edited, a hard guarantee never", () => {
  const [a, hard, tiers, w52] = presetRows([
    preset({}),
    preset({ key: "stop_price", title: "止损价", editable: false, hard_guarantee: true, levels: null }),
    preset({ key: "day_moves", editable: false, levels: null }),
    preset({ key: "new_high_52w", levels: levels([0, "remind"]) }),
  ]);
  assert.equal(a.canEdit, true);
  assert.deepEqual(a.levels, [{ level: "remind", label: "提醒", threshold: 25, text: "25" }]);
  assert.equal(a.unit, "%");
  assert.equal(hard.hard, true);
  assert.equal(hard.canEdit, false);
  assert.equal(hard.canReset, false);
  assert.equal(hard.levels, null);
  assert.equal(tiers.canEdit, false);
  assert.equal(tiers.canReset, false);
  assert.equal(w52.canEdit, false);
  assert.equal(w52.canReset, true);
});

test("restore default is offered per the server's `changed`, and on every editable default when it does not say", () => {
  assert.equal(presetRows([preset({})])[0].canReset, true);
  assert.equal(presetRows([preset({ changed: false })])[0].canReset, false);
  assert.equal(presetRows([preset({ changed: true })])[0].canReset, true);
  assert.equal(presetRows([preset({ overridden: false })])[0].canReset, false);
  assert.equal(presetRows([preset({ hard_guarantee: true, changed: true })])[0].canReset, false);
});

test("a disabled default stays listed and is not enabled; missing fields do not break a row", () => {
  const [off] = presetRows([preset({ enabled: false })]);
  assert.equal(off.enabled, false);
  const [bare] = presetRows([{ key: "x" }]);
  assert.equal(bare.title, "x");
  assert.equal(bare.enabled, true);
  assert.equal(bare.canEdit, false);
  assert.deepEqual(presetRows(null), []);
  assert.deepEqual(presetRows(["x", null]), []);
});

test("the yield line and the applies line", () => {
  assert.equal(yieldsLine(["INTC"]), "对 INTC 让位给你的规则");
  assert.equal(yieldsLine(["INTC", "AMD"]), "对 INTC、AMD 让位给你的规则");
  assert.equal(yieldsLine(["INTC", "AMD"], "en-US"), "Yields to your rule on INTC, AMD");
  assert.equal(yieldsLine([]), "");
  assert.equal(appliesText(["INTC", "AMD"]), "INTC、AMD");
  assert.equal(appliesText(["INTC", "AMD"], "en-US"), "INTC, AMD");
  assert.equal(appliesText("你的每只持仓"), "你的每只持仓");
  assert.equal(appliesText(null), "");
});

test("rule rows: status, last fired (sent or not), and the default it overrides", () => {
  const rows = ruleRows([
    { id: "r1", symbol: "INTC", text: "英特尔下跌 8%：提醒", status: "active", last_fired: "11-26 22:40（北京时间）", overrides_default: "默认的下跌分级对它不生效" },
    { id: "r2", symbol: "NVDA", text: "x", status: "expired", last_fired: null, overrides_default: false },
    { id: "r3", symbol: "AMD", text: "y", status: "done", overrides_default: true },
    { id: "r4", symbol: "TSLA", text: "z" },
  ]);
  assert.equal(rows[0].lastFired, "11-26 22:40（北京时间）");
  assert.equal(rows[0].override, "默认的下跌分级对它不生效");
  assert.equal(rows[1].fired, true);
  assert.equal(rows[1].lastFired, "");
  assert.equal(rows[1].override, "");
  assert.equal(rows[1].status.label, "已过期");
  assert.equal(rows[2].override, true);
  assert.equal(rows[2].fired, false);
  assert.equal(rows[3].status.active, true);
  assert.deepEqual(ruleRows(undefined), []);
});

test("threshold edits are checked by unit: above zero, share up to 100, a streak is whole days from 2, urgent above remind", () => {
  const one = [{ level: "remind" }];
  const two = [{ level: "remind" }, { level: "urgent" }];
  assert.deepEqual(checkThresholds("concentration", one, ["30"]), { levels: [{ threshold: 30, level: "remind" }] });
  assert.deepEqual(checkThresholds("concentration", one, ["12,5"]), { levels: [{ threshold: 12.5, level: "remind" }] });
  assert.ok(checkThresholds("concentration", one, [""]).error);
  assert.ok(checkThresholds("concentration", one, ["0"]).error);
  assert.ok(checkThresholds("concentration", one, ["-3"]).error);
  assert.ok(checkThresholds("concentration", one, ["abc"]).error);
  assert.ok(checkThresholds("concentration", one, ["101"]).error);
  assert.ok(checkThresholds("down_streak", one, ["1"]).error);
  assert.ok(checkThresholds("down_streak", one, ["3.5"]).error);
  assert.deepEqual(checkThresholds("down_streak", one, ["4"]), { levels: [{ threshold: 4, level: "remind" }] });
  assert.deepEqual(checkThresholds("volume_surge", one, ["150"]), { levels: [{ threshold: 150, level: "remind" }] });
  assert.deepEqual(checkThresholds("portfolio_drawdown", two, ["3", "5"]), { levels: [{ threshold: 3, level: "remind" }, { threshold: 5, level: "urgent" }] });
  assert.ok(checkThresholds("portfolio_drawdown", two, ["5", "5"]).error);
  assert.ok(checkThresholds("portfolio_drawdown", two, ["5", "3"]).error);
});

test("units of the editable defaults", () => {
  assert.equal(thresholdUnit("concentration"), "%");
  assert.equal(thresholdUnit("volume_surge"), "x");
  assert.equal(thresholdUnit("down_streak"), "days");
  assert.equal(thresholdUnit("new_high_52w"), "");
});

test("a refused write shows the server's Chinese reason, else a plain line by status", () => {
  assert.equal(watchWriteError(400, "这条是硬保证，不能关。"), "这条是硬保证，不能关。");
  assert.equal(watchWriteError(400, "bad_key"), "保存失败，请重试。");
  assert.equal(watchWriteError(403), "登录个人聊天后才能修改。");
  assert.equal(watchWriteError(404), "这条已不存在。");
  assert.equal(watchWriteError(500, { x: 1 }), "保存失败，请重试。");
});
