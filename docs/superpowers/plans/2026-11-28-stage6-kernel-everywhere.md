# 第六阶段：所有回合走新内核，删除旧流水线

设计稿 `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` 第十二节第 6 阶段：「所有 bot 切到新内核，删除旧流水线；写对外说明，更新 README。验收：尺子全项不低于基线。」

## 现状（11-28）

- 线上六个 bot 的 `engine` 都是 `v2`（11-24 晚起）。
- 还走旧流程的只有三处：
  1. **定时任务**（`agent_task_runner.run_unattended_turn` → `stream_workflow(unattended=True)`）：`graph._engine` 对无人值守的回合一律返回 None。线上目前只有一个定时任务，10-30 起停用。
  2. **不带 bot 的回合**（访客、目录模型直连）：`FINBOT_KERNEL_DEFAULT` 不是 `v2` 时走旧流程。过去 30 天只有访客的 13 条。
  3. **新建的 bot**：`engine` 默认 None，也走旧流程。
- 新内核还从旧流程里借用不少零件：`direct.py` 的显示用文字和执行结果整理（`act.py`、`press.py` 引用约 15 处）、`consent`、`evidence`、`tools` 等。

## 切片

| 片 | 做什么 | 档 |
|---|---|---|
| 6a | 上面三处都改走新内核；保留一键退回（`FINBOT_KERNEL_DEFAULT=v1`、`FINBOT_KERNEL_ROUTINES=off`、`FINBOT_KERNEL_V2=off`、bot 的 `engine=v1`） | 普通 |
| 6b | 删除旧流水线：把新内核还在用的零件挪出 `direct.py`，删掉旧回合本身（分类、路由、旧的回合循环、旧数字核查线）和只测旧回合的测试；退回开关一并去掉 | 高（改动面大，Fable 验收） |
| 6c | 对外说明、README 更新 | 小 |

6a 上线后至少跑过一个交易日、一次真实对话，再做 6b：6b 之后退回只能靠换回旧代码树。

## 6a 要做的

1. `graph._engine`：bot 写了 `v1`/`v2` 就用它；没写、或没有 bot，看 `FINBOT_KERNEL_DEFAULT`：只有正好等于 `v1` 才走旧流程，其余（包括不设）都走新内核。定时任务也按这条走；`FINBOT_KERNEL_ROUTINES=off` 时定时任务一律回旧流程。
2. `agent_bots._engine` 接受 `v1`。
3. 新内核的定时运行（`context.unattended`）：
   - 工具：读工具（不含 `search_x`，旧流程的定时运行也没有）、`act`、`notify_telegram`、技能、`plan`、`escalate`；没有 `ask`（没人回答）、没有 `handle_message`（没人插话）。
   - `act`：什么都不当场执行，每个提议放进他的收件箱「待你确认」（经运行器的 `action_sink`，和旧流程同一个格式，`agent_tasks.mint_card` 照常转卡片）；要他勾选材料的修订预测放不进收件箱，拒绝并说明。
   - `notify_telegram`：新内核接过旧流程的同名工具，服务端定收件人、加 bot 名、守每日条数、拒绝没编号的数字（`agent_telegram.notify`）。只给定时运行；他在对话里时直接在回答里说。
   - 提示：系统提示末尾加一段「定时任务、没人在看」的说明（没有 ask、写操作进收件箱、什么时候用 notify_telegram）。
4. 访客：系统提示加一句「只有所有者登录后才能做的事」，访客要求时直接说明。旧流程的访客提示有这一句，新内核没有。
5. 测试：新内核定时运行和访客的单元测试；测旧回合本身的老测试显式用 `v1`（它们在 6b 随旧回合删除）。

不做：定时运行的每次 token 上限（`token_budget`）——调用方今天不传，旧流程实际上也没有用到。

## 验收

- 相关测试 + 全量（最终提交上）。
- 影子环境：定时任务真跑一次（带一个会提议写操作的说明，看收件箱）、访客问一句、目录模型直连问一句。
- 尺子：基线题集一遍，不低于上次（85–86/86）。
- 审查：Sonnet。
