import assert from "node:assert/strict";
import test from "node:test";
import { botFilter, runsOfBot, scheduleSummary, statusKind, taskState, tasksOfBot } from "../src/routine-view.mjs";
import { runsLabel, scheduleLabel } from "../src/inbox-items.mjs";
import { RUNS, TASKS } from "../tools/shots/fixtures/routines.mjs";

test("a run's or task's last outcome has a tone: the success words are success, a failure or a run that did not happen is failure, the rest plain", () => {
  assert.equal(statusKind("ok"), "success");
  assert.equal(statusKind("quiet"), "success");
  assert.equal(statusKind("failed"), "failure");
  assert.equal(statusKind("skipped_no_model"), "failure");
  assert.equal(statusKind("skipped_no_bot"), "failure");
  assert.equal(statusKind("running"), "progress");
  for (const plain of ["no_evidence", "needs_input", "no_trigger", null, undefined, ""]) assert.equal(statusKind(plain), "neutral");
});

test("the schedule line is the old list's: the schedule, then the run limit", () => {
  for (const task of TASKS) assert.equal(scheduleSummary(task), [scheduleLabel(task), runsLabel(task)].filter(Boolean).join(" · "));
  assert.equal(scheduleSummary(TASKS[3]), "每 1 周（从 19:00 起） · 共 8 次");
  assert.equal(scheduleSummary(TASKS[0]), "工作日 08:30");
});

test("a task is paused or finished, or neither", () => {
  assert.equal(taskState({ enabled: true, finished: false }), null);
  assert.equal(taskState({ enabled: false, finished: false }), "paused");
  assert.equal(taskState({ enabled: false, finished: true }), "finished");
  assert.equal(taskState(undefined), "paused");
  assert.equal(taskState({ enabled: true, finished: false }, false), "paused"); // the switch as shown leads the server's answer
  assert.equal(taskState({ enabled: false, finished: false }, true), null);
});

test("the tasks and runs of one bot; no bot means all; a bot that is not a bot is no filter", () => {
  const bot = TASKS[0].bot_id;
  assert.deepEqual(tasksOfBot(TASKS, bot).map((t) => t.name), ["盘前新闻速览"]);
  assert.equal(tasksOfBot(TASKS, "").length, TASKS.length);
  assert.equal(tasksOfBot(null, bot).length, 0);
  assert.deepEqual(runsOfBot(RUNS, TASKS, bot).map((r) => r.task_name), ["盘前新闻速览", "盘前新闻速览"]);
  assert.equal(runsOfBot(RUNS, TASKS, "").length, RUNS.length);
  assert.equal(botFilter(bot, [{ id: bot }]), bot);
  assert.equal(botFilter("nope", [{ id: bot }]), "");
  assert.equal(botFilter(null, [{ id: bot }]), "");
  assert.equal(botFilter(bot, undefined), "");
});

test("手上的事: the tone and the one line of when", async () => {
  const { workStatusKind, workWhen } = await import("../src/routine-view.mjs");
  assert.equal(workStatusKind("done"), "success");
  assert.equal(workStatusKind("failed"), "failure");
  assert.equal(workStatusKind("running"), "progress");
  assert.equal(workStatusKind("queued"), "neutral");
  assert.equal(workStatusKind("stopped"), "neutral");
  const at = { started_local: "11-28 16:02", ended_local: "11-28 16:05", next_run_local: "11-29 08:00" };
  assert.equal(workWhen({ ...at, status: "running" }), "开始于 11-28 16:02");
  assert.equal(workWhen({ ...at, status: "queued" }), "下次 11-29 08:00");
  assert.equal(workWhen({ ...at, status: "failed" }), "11-28 16:05 结束");
  assert.equal(workWhen({ ...at, ended_local: null, status: "done" }), "开始于 11-28 16:02");
  assert.equal(workWhen({ status: "queued", started_local: null, ended_local: null, next_run_local: null }), "");
});
