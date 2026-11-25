# 交接：新内核做到第四阶段一半（2026-11-25 晚，Mac 上的 Claude → Muse 上的 Claude）

> 给接手的 Claude。owner 要求：简体中文、结论先行；可核验的结果才算完成。先读仓库根 `CLAUDE.md` 的三条准则和 `docs/claude/shared-memory.md`。

## 一、现在在哪

- 设计稿：`docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md`（阶段 0–6，第十二节是阶段表；第六节是记忆）。待办和每片的记录：`docs/finbot-backlog-2026-11-21.zh-CN.md`（第二十二节起是新内核，第三十六节是最新）。每片的实施计划在 `docs/superpowers/plans/`，验收报告在 `docs/reports/2026-11-stage-*.md`。
- **线上（黑豹 X2）已有：** 阶段 1 全部；阶段 2（2a 最新掌握、2b 公司事实、2c 问到就建档、2d 新旧/来源等级/指引）；阶段 3（3a 操作补全+防漏检查、3b 交办状态、3c 插话、3d 小助手——开关 `FINBOT_HELPER` 默认关）；阶段 4 的 4a（你的看法 `record_view`/`drop_view`、`read_turn`）、4b（每月整理，`app/memory_review.py`、记忆日历 `app/memory_schedule.py`）、4c（每季沉淀，`app/memory_settle.py`）。PR #33（2a–4a）、#34（4b）、#35（4c），main 在 `81656ca`。
- **线上默认关着的：** `FINBOT_HELPER`（小助手，等尺子量过再开）、`FINBOT_DUTY_MODE=shadow`（值班只记录不发）。打开都要 owner 点头。
- 第一次每月整理约在 12-25（或 owner 发满 40 条消息时提前）；第一次每季整理 2027-02-15。

## 二、接下来（第四阶段剩下的三片）

1. **4d 复盘**（设计稿 §6.3）：每季回看 owner 以前对公司的看法（`owner_views` 的历史版本），哪些成立了、哪些没有、当时的理由还在不在。建议挂在 4c 的每季任务上（同一个记忆日历），一次模型调用，输入由代码拼好（看法原文+日期、当时与现在的价格、之后的最新一季数字），输出里出现的每个数字都必须出自输入（参考 `app/agent_context_summary.py` 的数字核对）；结果存表、在公司页的看法历史下显示，并进每季那条变更说明。
2. **4e 「它眼中的你」页面**：一页列出记住的一切和推测，可以改、删、整体导出（记忆页已覆盖大部分，缺导出、缺「看法+画像+推测」的统一视图）。
3. **4f 角色模板**：「短线」「定投」「基金经理」各一套起步设置（盯防条件、简报格式、常用技能），只是初始记忆和配置，不是代码分支。

之后是阶段 5（后台值班和留痕）和阶段 6（全部切换、删旧流水线）。

## 三、怎么做（这几天跑顺了的流程）

- 每片：写计划（`docs/superpowers/plans/日期-名字.md`，带 Global Constraints 和 Review Focus）→ 用子代理逐项实施（实施和审查用 Sonnet，Opus 只在 owner 点名时用）→ 每项审查 → 整体审查一次、修一轮 → **在最终提交上跑全量**（约 4.5 分钟）→ 影子环境用真实数据实测 → 写报告 → PR → **自己确认 CI 通过**（Auto-fix 只在失败/冲突/评论时叫你，通过不会通知）→ 合并 → 发布。owner 的长期授权：CI 过了就合并发布。
- 全量测试：`.venv-rag/bin/python -m pytest -q -W ignore tests/`。一直有两项顺序相关的失败（`test_sw1_existence_knowledge::test_t39…`、`test_sw1b_sample_aggregate::test_b17…`），单独跑能过，不是新问题。
- 前端：在一个独立副本里装依赖跑 `npm run test:i18n`、`npx tsc -b`、`npm run build`、截图 `frontend/tools/shots`（`node smoke.mjs --only <前缀>`；全量冒烟要几个小时，别跑）。

## 四、黑豹上的发布和影子环境（需要能 ssh 到盒子）

- 发布（archive-swap，先 API）：`git archive <合并提交>` 传到 `/opt/finbot/incoming-<sha>.tar.gz` → 先跑 `/opt/finbot/bin/finbot-db-backup.sh` 手动备份 → 解到 `/opt/finbot/src-new`，拷 `src/.env` 和 `rsync src/data/` → `systemctl stop finbot-api` → `mv src src-oldNN`（现在最大是 `src-old88`）→ `mv src-new src` → 起 API，等 `/health` → 依次重启 rag-slim、telegram、wechat、sentinel → 看 `journalctl -p warning` 和公网 `/health`。**不要回滚到带 `pre-s0-DO-NOT-ROLLBACK` 的旧树。** 远程脚本里 `set -e` 时 `r=$(curl …)` 失败会直接退出，用 `|| true`。
- 前端：合并后 Pages 会自动部署；常见失败「No artifacts named github-pages」，用 `gh workflow run "Deploy frontend to GitHub Pages" --ref main` 新开一次。
- 影子：`/opt/finbot/bin/ruler_shadow.sh up v2|status|down`（用最新夜间备份恢复 `finbot_ruler`，9031 端口）。要测某个分支：`git archive` 传上去解到 `/opt/finbot/ruler-src` 后 `systemctl restart finbot-ruler-api`。在影子里跑 Python 一定在 `/opt/finbot/ruler-src` 下、带 `PYTHONPATH=.`（否则会导入线上代码），并先 `. ./.env && . /opt/finbot/ruler.env`。影子里没有桥，通道提醒只进发件箱不会发出去；SEC 代码表要先 `archive_subjects.refresh_ticker_list()`。跑完 `down`。
- 尺子：`python -m ruler.run run --suite ruler/suites/baseline-v1.json --out … --parallel 2`（约 11 分钟），`compare --base … --new …`。同一天同一份备份跑一遍线上代码当对照，比和旧基线比准。11-25 对照：线上 6.3 秒、整串 6.6 秒、86/86。

## 五、规矩（owner 定过、或今天吃过亏的）

- 删除、不可逆、改 owner 自己的设置（备用模型、渠道、开关）先问；其他直接做，不要反复问 yes/no。不读 `passwords.md`，不替 owner 输密码或登录码，密钥由 owner 自己放到服务器上，不在输出里显示。
- 改启动参数、根分区挂载、fsck、网络之前，先确认有带外通道（11-25 就是这样把盒子弄失联的，见 `docs/incidents/2026-11-25-heibao-boot-failure.md`）。
- 动手前先看清在哪个分支、导入的是哪份代码；说「测试通过」只基于最终提交上跑出来的结果；远程停进程不用 `pkill -f`（会把自己的 ssh 会话杀掉）。
- 要根本解法不要补丁（加规矩、加清单都算补丁）；花费不是砍功能的理由，做成可配置。

## 六、等 owner 定的

- 每天把备份同步到盒子外面（建议 Mac 每晚拉一份，保留 14 份；目前只手动拷过）。
- 小助手要不要用尺子量过后打开；值班要不要从 shadow 改成真发。
- 测试 bot 的对话会被每月整理当成 owner 的话（推测都要他确认，暂未另加「不计入记忆」）。

## 七、已知小问题

- 默认 bot 那条很长的老对话里，模型偶尔会说「已记下」却没调用工具、问「手上有什么事」不调 `list_work`；新对话里重复多次都正常（套件 `ruler/suites/probe-views-work.json`）。
- 有了「系统最新掌握」后，模型常在不相关的问题里顺带讲价格，回答偏长，之后调。
- 截图夹具缺 `GET /agent-chat/channels` 和 `/channels/deliveries`；「模型增删改」冒烟自 1f-1 加价格字段后一直不过；`owner-views` 冒烟偶发超时。
- `docs/claude/shared-memory.md` 里的「生产拓扑/模型」写于 11-13，部分已过时；按它的规矩由操作员更新，不要自己改。
