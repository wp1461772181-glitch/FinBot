# FinBot 个人金融助手：开发计划

> **给执行这份计划的 Claude Code：** 你没有参与之前的讨论，这份文档就是全部依据。按任务顺序做，复选框用来记进度；每个任务测完就提交并发布（见第五节）。和用户沟通用中文。如果环境里装了 superpowers 插件，可以用 `superpowers:executing-plans` 执行。

**目标：** 把 FinBot 从股票研究工作台改成个人金融助手：知道用户持有什么，全天盯着持仓，财报和股价出事时主动提醒；同时修掉用户提出的 bug 和体验问题。

**架构：** 数据库放 Supabase，API、Telegram 桥和哨兵常驻 Muse，向量库和向量模型留在用户的 Mac，前端仍在 GitHub Pages。

**技术栈：** Python 3.12、FastAPI、LangGraph、SQLAlchemy、PostgreSQL；React 19、TypeScript、Vite、Node 22。

**仓库：** https://github.com/wp1461772181-glitch/FinBot

---

## 一、为什么做这些

2026-10-29 美东盘后 Intel 发财报，10-30 收盘 65.76（前一日 92.07，跌 28.6%）。用户是刷抖音才知道的，FinBot 毫无作用。查库和日志后的原因：

| 原因 | 证据 |
|---|---|
| 机器睡着了 | 监控都跑在 MacBook 上；`official_monitor_runs_v2` 显示连续 6 晚每晚停 10–16 小时，正好盖住美股盘中和盘后财报 |
| 发现得晚 | 8-K 于 10-29 20:08 UTC（美东 16:08）进 SEC，FinBot 10-30 00:45 UTC 才发现，晚 4.6 小时 |
| 发现了也没读 | 这份 8-K 的 `content_status=not_fetched`；现有申报提醒只说"SEC 收到 X 的 8-K" |
| 没有提醒规则 | 唯一的例行任务是已停用的「每小时苹果新闻」；研究队列不会触发提醒 |
| 行情只有日线 | Yahoo `interval=1d`，每小时刷新；价格提醒只看收盘价是否穿过用户设的价位 |

## 二、最终架构

```text
浏览器（GitHub Pages）--HTTPS--> Muse: API（含例行任务、SEC 监控、行情刷新）--> Supabase（PostgreSQL）
Telegram <--> Muse: Telegram 桥 --> API
Muse: 哨兵（API 和数据库都挂了也能发提醒）；探活 API，按需拉起预测 worker
Muse: API --Tailscale--> Mac: 检索服务（BGE-M3、重排、Milvus）+ 建索引
```

Mac 睡着时，只有知识库检索和建索引不可用，其他都照常。

Muse 的可用内存在 0.6–1.3 GB 之间波动，夜里低谷约 595 MB，而夜里正是美股时段。内存预算：

| 进程 | 内存 | 是否常驻 | 依据 |
|---|---|---|---|
| API（合并例行任务、SEC 监控、行情刷新） | 约 290 MB | 常驻 | 不加载向量模型时导入代码的实测下限，运行时会涨，上线后要实测 |
| Telegram 桥 | 约 75 MB | 常驻 | 实测 |
| 哨兵 | 15–60 MB | 常驻 | httpx + sqlite3 实测 32 MB；只用标准库、不导入 `app` 时更低 |
| 公网入口 | 约 25 MB | 常驻 | Muse 的估算 |
| 预测 worker | 约 124 MB | 有任务才起 | 实测 |

稳态约 400–450 MB，worker 运行时约 530–575 MB。余量很薄，所以有两条硬规则：**可用内存不足 200 MB 时不拉起 worker；给 worker 设内存上限，内存不够时先杀它，不能杀哨兵。**

## 三、全局约束

- 只做美股，币种只有美元。
- 不碰交易：不接券商下单，不替用户买卖。提醒结尾保留"只是提醒，不是买卖建议"。"加仓"只提醒用户自己预设的计划。
- 语义判断交给模型，不写正则猜用户的话。规则只用于权限和依据校验。这是用户明确的取向。
- 写操作一律走确认卡。持仓只有所有者能看，访客模式看不到。
- 数字要有来源：比较结果用代码算好再给模型，回答里的数字带引用。
- 这是用户面试要讲的作品：每块记"改之前、改之后"的实测数字（第八节），只写实测值。
- 代码跟周围保持一致，前端这些文件是紧凑的长行风格，不要顺手重排。
- 提交只写明确路径，不提交 `.env`、`.local/`、`data/`、`frontend/node_modules`。提交信息沿用仓库习惯，如 `feat(前端): …`、`fix(agent): …`。
- 不打印、不提交任何密钥。`APP_API_ACCESS_KEY` 不能换：凭证加密的密钥由它派生（`app/secret_box.py:35`），换了库里的模型 key 和 Telegram token 就都解不开了。
- 用户偏好：删除和不可逆操作要先问，其他不要问 yes/no，直接做。汇报要短，没做完、没验证的如实说。简单的事别搞复杂。

## 四、容易出事的地方

这些情况需求里没明说，但最容易坑到用户，对应的测试写在括号里的任务中：

1. **拆股**：价格一夜少九成，不能当成暴跌提醒，也不能把持仓盈亏算错（Task 6、Task 11）。
2. **休市、停牌、盘前没成交**：Yahoo 返回空值或旧数据，不能产生信号（Task 11）。
3. **重复和无关的 8-K**：只认 2.02 项，按 accession 去重，进程重启后也不重发（Task 9）。
4. **Mac 睡着**：知识库检索 5 秒内返回离线提示，这一轮照常回答（Task 4）。
5. **持仓的异常输入**：卖出超过持有、确认卡按两次、可用资金变负（Task 6）。

## 五、测试与发布

**测试：**
- 后端：`python -m pytest -q`。`tests/conftest.py` 会忽略 `DATABASE_URL`，自己建一个一次性的测试库，要求 `TEST_DATABASE_URL` 的库名以 `test_` 开头。**绝不能把它指向 Supabase。**
- 前端：`cd frontend && npm run test:i18n && npm run build`。新的 `frontend/scripts/*.test.mjs` 要加进 `package.json` 的 `test:i18n` 列表，否则不会跑。
- **Muse 内存紧**：先看 `free -m`。可用内存不足 1.5 GB 时，不要在本机跑全量 pytest 和 `npm run build`，会挤掉线上进程。本机只跑相关测试，全量交给 CI（`.github/workflows/ci.yml`，推送 main 和 PR 都会跑）。
- 已知问题：`tests/test_material_sync_acceptance.py::test_sec_sync_cycles_cover_both_sides…` 全量跑偶发失败，单独跑稳定通过。
- 真实模型跑测用模型目录里配好的 DeepSeek（Token Plan，不计 token），这部分花销不用在意。

**发布：**
- 改完、测完直接发布，不用问。
- 推送 main 且改到 `frontend/**` 时，`deploy-pages.yml` 会自动发布前端，所以前端用到新接口时，要在接口缺失时也能正常显示，并且推送后马上部署后端。
- **Task 4 切换之前**，线上还在 Mac，你部署不了后端。Task 1 只改前端，推送即上线。Task 2、3 的后端改动可以先合进 main，随切换一起上线；如果切换推迟，让用户在 Mac 上跑 `python scripts/deploy.py --backend-only`。
- **Task 4 切换之后**，用 Task 4 写的 `scripts/deploy_muse.sh` 发布。

## 六、日程

今天 11-02 开工：

| 日期 | 任务 | 用户要做的 |
|---|---|---|
| 周一 11-02 | Task 0、1、2、3 | 今晚合上 Mac 跑过夜心跳；注册 Supabase |
| 周二 11-03 | 看心跳结果；Task 4、5；后台准备 Task 8 的数据 | 把 `.env` 等文件传到 Muse；做 Task 4 的 Mac 侧步骤 |
| 周三 11-04 | Task 6、7 | 试用持仓录入 |
| 周四 11-05 | Task 8 跑完；Task 9 | — |
| 周五 11-06 | Task 10、11、12 | 注册 Pushover，把 key 填进设置页 |
| 周六 11-07 | Task 13、14 | — |
| 周日 11-08 | Task 15、16；全量回归 | 整体试用 |

- AMD 和苹果上一次发财报分别是 8-04 和 7-30，约 13 周一次，这周很可能会发。Task 9 赶得上就实战，赶不上就等它们发完拿来回放验收。
- Task 7、13、15 都要改 `app/agent_workflow/direct.py`，按顺序做，不要并行。
- **来不及时先砍**：Task 15 的结构化摘要（先只做预算和 `/压缩`）、Task 13（可顺延到下周）。其他不砍。

---

## 七、任务

### Task 0：核实 Muse 环境

这是后面架构的前提。用户的 Mac 上也装着 Muse 客户端（bundle id `com.meta.endo`），所以要确认常驻进程不是跑在 Mac 上。

- [ ] 运行 `uname -a`、`hostname`、`free -m`、`df -h`。必须是 Linux，且不是用户的 Mac。**如果显示 Darwin，立刻停下告诉用户，方案不成立。**
- [ ] 确认能访问 SEC（带 `User-Agent`）、Yahoo chart、`api.telegram.org`、模型接口。
- [ ] 确认退出会话后进程还在，并确定自启动方式（systemd、supervisor 或其他），以及能否安装 Tailscale。
- [ ] 起一个每分钟写时间戳的心跳脚本跑一整夜，请用户合上 Mac。第二天检查，把任何超过 3 分钟的空档报告给用户。

**验收：** 上面都通过才进入 Task 4。不通过就告诉用户，备选是租一台 1–2 GB 内存的海外小云主机，后面的任务不变。Task 1–3 不受影响，照常做。

### Task 1：切换 bot 不丢草稿、不中断回答

**现象：** 在一个 bot 的输入框打字后切到别的 bot，字就没了；一个 bot 正在回答时切到别的 bot，回答就断了。

**原因：** `frontend/src/AgentChatPanel.tsx:142` 的 Provider 里，`draft`、`messages`、`state` 全局只有一份。切换走 `selectBot`（`:253`）到恢复对话（`:229`），这里调 `lifecycle.current.begin()`，而 `agentChatLifecycle.js` 的 `begin` 会 abort 上一个请求，服务端随后收到 `CancelledError`（`app/agent_chat_stream.py:522`）。恢复对话和 `clear` 还会 `setDraft("")`。服务端的锁是按对话加的（`agent_chat_stream.py:399`），不同 bot 同时回答没有问题，所以只改前端。

**文件：**
- 新建：`frontend/src/chat-lines.mjs`、`frontend/src/chat-lines.d.mts`、`frontend/scripts/chat-lines.test.mjs`
- 修改：`frontend/src/AgentChatPanel.tsx`、`frontend/src/BotPages.tsx`（`BotRailList`，`:100`）、`frontend/package.json`

**接口：**
```js
lineKey(bot, conversationId)        // "bot:<id>"、"conv:<id>" 或 "local"
loadDraft(line, storage)            // 键 market-evidence-agent:draft:<line>:v1，读写都包 try/catch
saveDraft(line, text, storage)      // 空串就删键
createLineStore()                   // { get(line), update(line, patch), running(), markSeen(line) }
```

**决定：**
- 每条对话线一份独立状态（消息、状态、草稿、历史游标），并且有自己的 `AgentChatLifecycle`。
- 切换只改"正在看哪条线"，不 abort。只有同一条线再次发送或按停止才 abort。
- 回到正在回答的线，不重新拉历史，接着显示；回到空闲的线，按现有方式恢复。
- 草稿按线存 localStorage，发送后清掉，刷新页面后还在。
- 侧栏上，回答中的 bot 显示小圆点，后台答完显示"新回答"，打开后清除。这是前端本地状态，和服务端的 `bot.unread` 分开。
- 刷新页面或关闭标签页仍会中断回答，这次不处理。访客模式只有一条线，行为不变。

**测试**（`chat-lines.test.mjs`）：
- [ ] `草稿切换后还在`：A 写草稿，切到 B 再切回，`loadDraft` 得到原文。
- [ ] `切换不中断`：A 运行中切到 B，A 的 `controller.signal.aborted === false`。
- [ ] `同线再发才中断`：A 再次发送，上一个 controller 被 abort。
- [ ] `后台完成打标记`：正在看 B 时 A 完成，A 标记为新回答；`markSeen(A)` 后清除。
- [ ] `存储报错不影响使用`：storage 抛异常时 `loadDraft` 返回空串。
- [ ] 原有的 `scripts/agent-chat-lifecycle.test.mjs` 保持通过。

**验收：** 在 A 打字，切到 B 再切回，字还在；刷新后也在。问 A 一个长问题，切到 B 再问一个，两个都答完；切回 A 能看到完整回答和思考过程；服务端日志没有 `CancelledError`。

### Task 2：技能能存进技能库

**现象：** 用户让 bot 写技能并加入库里，`draft_skill` 两次都返回 `not_asked`。

**原因：** `app/agent_skills.py:43` 的 `SAVE_ASK` 正则要求原话里出现"存成技能"这类说法，"帮我把这个 skill 新增一下"和"写一个……skill"都匹配不上。这正是用词面规则替模型做语义判断。而且放行后也只是草稿，还要用户去技能页点保存。

**文件：** 修改 `app/agent_skills.py:43,420-430`、`app/agent_tool_catalog.py:278`、`app/agent_workflow/consent.py:150`、`app/agent_workflow/direct.py`（`:184` 分类器示例、`:1752`、`:2656`）、`frontend/src/agent-tool-labels.mjs`、`frontend/src/locales/en-US.json`。

**决定：**
- 删除 `SAVE_ASK` 和 `owner_words` 参数。工具改名 `save_skill`，级别改为 `reversible`，确认卡写法照 `create_routine`（`ROUTINE_TOOLS`）。
- 卡片显示名字、什么时候用、步骤、允许的工具，按钮是"保存并启用"（`status=active`）、"存为草稿"（`status=draft`）、"取消"。
- 在分类器示例里加上"把这个 skill 新增一下""写一个异动归因的 skill""存成技能"，都给 `requested_actions: ["save_skill"]`。
- 技能只会收窄可用工具，这条不变；目录外的工具照旧拒绝。

**测试：**
- [ ] `tests/test_agent_skills.py`：不同说法都不再因措辞被拒；按"保存并启用"后 `status=active` 且 `/名字` 可用；按"存为草稿"后不出现在可用列表。
- [ ] `tests/test_telegram_consent_write.py`：Telegram 按钮走同一个处理，确认后技能入库。
- [ ] `tests/test_agent_tool_labels.py`：`save_skill` 有显示名。

**验收：** 三种说法都弹出确认卡，按下后技能页出现并且能用。

### Task 3：价格精度（`calculation_input_unbound`）

**原因：** Yahoo 给的是单精度浮点，92.07 存成了 92.06999969482422，引用里也原样显示。`calculate` 要求输入和来源数字完全相等（`app/agent_workflow/calculation.py:26`），模型传 92.07 就永远绑不上。答案校验也会因此把正确的数字判成无依据。

**决定：不改库里的历史价格。** `market_prices` 的 `content_hash` 按原始浮点算（`app/market_data_ingestion.py:34`），预测版本的 `price_input_manifest` 也记录了它（`app/forecast_v2_processor.py:455`）。改存量会让行情刷新产生一批假修订，也破坏预测回放。只改显示和比对。

**文件：** 修改 `app/agent_workflow/evidence.py:365` 一带（已保存价格的 `quote`、`figures`）、`app/agent_workflow/calculation.py`（`calculate`、`bindable_values`）。

**接口：**
```python
format_price(value: float) -> str            # round(value, 4) 后去掉多余的零：92.06999969482422 -> "92.07"
matches_source(value: Decimal, numbers: set[Decimal]) -> bool
# 完全相等，或 value 至少 2 位小数且等于来源数字按 value 的小数位四舍五入的结果
```

**测试**（`tests/test_agent_calculation_units.py`）：
- [ ] `test_rounded_price_binds`：来源 `92.06999969482422`，`92.07` 通过，`92.1` 和 `92.08` 抛 `calculation_input_unbound`。
- [ ] `test_price_quote_is_rounded`：已保存价格的引用里是 `92.07`，不含 `92.0699`。
- [ ] `test_rounded_price_not_flagged`：回答写"收盘 92.07 [1]"，`unsupported_number_values` 返回空。
- [ ] `test_exact_figures_unchanged`：财报数字（如 165.13）的绑定行为不变。

**验收：** 问"INTC 10-29 到 10-30 跌了多少"，一次算对，不再报 `calculation_input_unbound`。

### Task 4：迁到 Supabase 和 Muse

数据库选 Supabase 免费版，不选 Neon。Neon 免费版每月只有 100 计算小时，用完就暂停，而 Telegram 桥大约每分钟读一次库，按最小规格约 17 天就会用完。Supabase 免费版的代价：上限 500 MB（现在 216 MB）、没有自动备份、连接池只有 15。

**用户先做：** 注册 Supabase，选离 Muse 最近的地区建项目；把 `.env`、`data/personal-chat-login.json` 用安全的方式传到 Muse，不要走聊天，不要提交。

**4.1 数据库连接**
- [ ] 改 `app/database.py:11`：环境变量 `DB_POOL_SIZE`（默认 5）、`DB_MAX_OVERFLOW`（默认 10）、`DB_CONNECT_TIMEOUT`（默认 10 秒，放进 `connect_args`），加 `pool_recycle=300`。现在没有连接超时，连不上时会卡很久。
- [ ] 线上配置：API 为 5 + 3，其他进程为 1 + 1，总连接数不超过 15。
- [ ] 连接地址：Muse 有 IPv6 就用直连，否则用 Session pooler（端口 5432）。**不能用 Transaction pooler（6543）**，代码里有会话级咨询锁：`app/official_monitor_v2.py:351`、`app/agent_task_runner.py:520`、`app/agent_workflow/actions.py:58,183`。Supabase 的连接细节是凭记忆写的，以控制台为准。
- [ ] 写 `scripts/check_db_session_lock.py`：连接 A 拿到 `pg_try_advisory_lock` 后，连接 B 拿不到；A 断开后 B 能拿到。切换前必须通过。

**4.2 拆出本机检索服务**
- [ ] 在 Mac 上跑 `scripts/run_retrieval_service.py`（FastAPI，`POST /retrieve`、`GET /health`，校验 `X-Retrieval-Token`），由它加载 BGE-M3、重排和 Milvus，并负责建索引。
- [ ] API 设了 `RAG_REMOTE_URL` 时，`app/knowledge/runtime.py` 的 `start_runtime` 返回 `RemoteKnowledgeRuntime`，接口和 `KnowledgeRuntime` 相同，不导入 torch。权限范围、时间截止（`research_context`）必须随请求传过去。连接超时 2 秒，总超时 15 秒。
- [ ] 连不上时抛 `KnowledgeOffline`，工具返回 `knowledge_offline` 和提示，这一轮继续回答。
- [ ] `scripts/run_api_server.sh` 在 `RAG_REMOTE_URL` 存在时不能选 `.venv-rag`。
- [ ] 测试 `tests/test_remote_retrieval.py`：`test_offline_fails_fast`（地址不通时 5 秒内抛 `KnowledgeOffline`）、`test_scope_is_forwarded`、`test_no_torch_import`（子进程导入后 `torch` 不在 `sys.modules`）。

**4.3 合并后台任务**
- [ ] 新建 `app/background.py`：`BACKGROUND_LOOPS=true` 时在 API 进程里用 asyncio 循环调用现有入口，例行任务每 300 秒，SEC 监控和行情刷新每 3600 秒，都放 `to_thread`，单个循环出错不影响其他循环。
- [ ] 预测 worker 不常驻，由哨兵用 `python -m app.forecast_worker --once` 拉起（`app/forecast_worker.py:255`），见 Task 5。

**4.4 部署脚本和公网入口**
- [ ] 写 `deployment/muse/` 下的自启动配置和 `scripts/deploy_muse.sh <sha>`：拉代码、装依赖（不装 `requirements-rag.txt`）、重启、等 `/health`，失败就回到上一个 sha。
- [ ] 运行时会写的 `config/news_sources.yaml` 不能让 `git pull` 冲突，放到数据目录，用环境变量指向。
- [ ] 必须走公网，因为网页在 GitHub Pages 上。首选 Tailscale：一个进程同时解决连 Mac 和对外 HTTPS（Funnel，现在就是这么用的）。装不上才用 Cloudflare Tunnel，那需要用户有域名，并且要另外解决连 Mac 的通路。

**4.5 切换**（依次执行，标"Mac"的步骤交给用户）
- [ ] 跑 `scripts/check_db_session_lock.py`。
- [ ] Mac：停服务冻结写入，`launchctl bootout` 掉 `com.market-evidence-agent` 的 `api`、`forecast-worker`、`telegram-bridge`、`agent-tasks`、`official-sec-monitor`、`market-data-refresh`。plist 留着回滚用。Telegram 同一个 token 只能有一个进程长轮询，所以必须先停 Mac 上的桥。
- [ ] Mac：`pg_dump -Fc --no-owner --no-privileges` 导出，`pg_restore` 到 Supabase，核对主要表的行数。Mac 上的库保留不动。
- [ ] 在 Supabase 关掉 Data API，并给 `public` 下所有表打开 RLS。否则这些表可能经它的自动 REST 接口暴露；应用用 `postgres` 角色连接，不受影响。选项名以控制台为准。
- [ ] 启动 Muse 上的 API、Telegram 桥、哨兵和公网入口。
- [ ] Mac：启动检索服务，`RAG_INDEXING_ENABLED=true` 只留在 Mac。
- [ ] 改 GitHub Actions 变量 `VITE_API_BASE_URL`，重新发布前端。`CORS_ALLOWED_ORIGINS` 保持 `https://wp1461772181-glitch.github.io`。
- [ ] 冒烟：访客提问、所有者提问、Telegram 提问、读预测、读材料、知识库检索。
- [ ] Mac：加每周一次的 `pg_dump` 备份到 `data/backups/`（每次约 216 MB，Supabase 免费版每月出口流量 5 GB，不要每天备）。

**回滚：** 把 `VITE_API_BASE_URL` 改回去、重新启动 Mac 的 launchd 服务、停掉 Muse 上的进程。切换后 Supabase 里的新数据要先导回 Mac 再回滚。

**验收：**
- [ ] 连续 48 小时，SEC 监控运行间隔不超过 2 小时（之前每晚停 10–16 小时）。
- [ ] Mac 睡着时，普通提问和网页正常，知识库检索 5 秒内提示离线。
- [ ] 记录 Muse 上各进程的实际内存和可用内存低谷。
- [ ] 每轮回答耗时对比改之前（中位数 22 秒，P90 65 秒）。明显变慢就查每轮查库次数和 Muse 到 Supabase 的延迟。

### Task 5：哨兵骨架

哨兵是最后一道防线，要小，要独立。**只用标准库（`urllib`、`sqlite3`、`json`、`statistics`、`zoneinfo`），不导入 `app`。**

**文件：** 新建 `sentinel/main.py`、`sentinel/store.py`（SQLite，`data/sentinel.db`）、`sentinel/notify.py`、`sentinel/signals.py`、`app/sentinel_bridge.py`、`tests/test_sentinel_core.py`。

**接口：**
```python
# app/sentinel_bridge.py
write_sentinel_snapshot(owner_hash: str) -> None
# 写 data/sentinel-config.json（权限 0600）：持仓、预设计划、研究队列、总资产、Telegram 和 Pushover 配置。
# 这些数据变化时和 API 启动时调用；哨兵发现文件的 mtime 变了就重新加载。API 挂了它仍有最后一份。

# API 新增，只接受本机请求，并校验 X-Sentinel-Token（环境变量 SENTINEL_TOKEN）
POST /agent-chat/internal/sentinel/events          # earnings_detected、alert_posted
GET  /agent-chat/internal/sentinel/pending-forecast-jobs
```

**决定：**
- 每件事一个线程，互相隔离，一个出错不能影响提醒。
- 每 60 秒探活 `/health`，连续 3 次失败就直接发 Telegram 告诉用户。重启进程交给自启动配置。
- 每 60 秒查待处理的预测任务：有任务、没有 worker 在跑、`/proc/meminfo` 的 `MemAvailable` ≥ 200 MB，才拉起 `python -m app.forecast_worker --once`，并设内存上限。
- 每分钟请求一次 `SENTINEL_HEARTBEAT_URL`（用户注册的外部心跳监控），超过 5 分钟没报就由外部服务通知用户。
- 发给 API 失败的事件存进 SQLite 的重试队列，恢复后补发。

**测试：**
- [ ] `test_sentinel_does_not_import_app`：子进程导入 `sentinel.main` 后，`sys.modules` 里没有 `app`。
- [ ] `test_snapshot_reload_on_mtime`。
- [ ] `test_worker_not_started_when_memory_low`：`MemAvailable` 小于 200 MB 时不拉起。
- [ ] `test_one_loop_failure_does_not_stop_others`。

**验收：** 手动停掉 API，3 分钟内收到 Telegram；哨兵的实际内存记录下来。

### Task 6：持仓第一版

用户说的"自由现金流"指**自己可用于加仓、补仓的钱**，产品里叫"可用资金"，避免和公司财报里的自由现金流混淆。

**文件：** 新建 `app/portfolio.py`、`app/portfolio_api.py`、`frontend/src/PortfolioPage.tsx`、`frontend/src/portfolio-items.mjs`（和 `.d.mts`）、`frontend/scripts/portfolio-items.test.mjs`、`tests/test_portfolio.py`。修改 `app/agent_chat_models.py`、`app/main.py`、`app/agent_tool_catalog.py`、`app/agent_tools.py`、`app/agent_workflow/direct.py:184`（分类器示例）、`frontend/src/App.tsx`、`frontend/src/BotPages.tsx`、`frontend/src/workspace-cards.mjs`、`frontend/src/WorkspaceCards.tsx`、`frontend/src/agent-tool-labels.mjs`、`frontend/src/locales/en-US.json`。

**数据表：**
```text
portfolio_transactions: id, owner_hash, symbol(现金类为空), kind, quantity, price, fee, amount, ratio, occurred_on, note, created_at
  kind 取值：opening、buy、sell、dividend、split、deposit、withdraw、cash_adjust
portfolio_plans: owner_hash, symbol, plan_text, add_price, stop_price, target_price, updated_at
```

**计算规则**（纯函数，用 `Decimal`）：
- 平均成本 = 持仓成本 ÷ 股数，买入金额含手续费；卖出按比例减少持仓成本，平均成本不变。
- 摊薄成本 =（累计买入含手续费 − 累计卖出净得 − 分红）÷ 当前股数。
- 已实现盈亏 = 卖出净得 − 卖出部分的持仓成本。
- 浮动盈亏 = 股数 ×（最新价 − 平均成本）。今日盈亏 = 股数 ×（最新价 − 昨收），当天有成交的标注"仅供参考"。
- `split`：股数乘 `ratio`，平均成本除 `ratio`。
- 可用资金 = deposit + cash_adjust − withdraw − 买入（含手续费）+ 卖出净得 + 分红。`opening` 不动可用资金。用户手填可用资金时，写一笔 `cash_adjust` 补差。
- 最新价取 `market_prices`，并显示数据日期。

**接口：**
- API 前缀 `/agent-chat/portfolio`，用和 `app/agent_bots_api.py` 相同的所有者校验：`GET` 汇总、`POST /transactions`、`DELETE /transactions/{id}`、`PUT /plans/{symbol}`、`PUT /cash`。写入后调 `write_sentinel_snapshot`。
- 读工具 `query_portfolio`；写工具 `record_trade`、`set_available_funds`、`set_position_plan`（`reversible`，走确认卡，加进 `OWNER_ONLY`）。`query_portfolio` 的结果带 `source_type=portfolio` 的引用，让回答里的数字能通过校验。

**界面：** 侧栏主入口"持仓"（和例行任务并列，手机端也有，地址 `#portfolio`）；工作区新增卡片"我的持仓"并放进默认布局。显示平均成本和摊薄成本（平均成本为主）、浮动和今日盈亏、仓位占比、可用资金。每只持仓可写文字计划和补仓价、止损价、目标价。第一版只做手填和对话录入，券商对账单导入以后再做。

**测试**（`tests/test_portfolio.py`）：
- [ ] `test_cost_and_realized`：买 100 股 @80（手续费 1），卖 40 股 @100（手续费 1）。剩 60 股，平均成本 80.01，已实现 798.60，摊薄成本 66.70。
- [ ] `test_available_funds`：入金 10000、买 100 @80（费 1）后是 1999；`opening` 不改变它。
- [ ] `test_sell_more_than_held_rejected`：报错，不写入。
- [ ] `test_confirm_card_replay_no_double_entry`：同一张确认卡按两次只记一笔。
- [ ] `test_negative_funds_warns`：可用资金会变负时，仍可记录，但结果里带提示。
- [ ] `test_split_adjusts_position`：1 拆 2 后股数翻倍，平均成本减半，浮动盈亏不变。
- [ ] `test_guest_cannot_read`：访客读持仓被拒，工具不提供。
- [ ] `frontend/scripts/portfolio-items.test.mjs`：金额和百分比显示。

**验收：** 网页手填和对话说"我买了 100 股 INTC，成本 80"（出确认卡）都能记录；"我今天赚了多少""INTC 补 50 股要多少钱、可用资金够不够"都答对，数字带出处。

### Task 7：闸门改成只标注、不删内容

**现象：** 10-31 NewsBot 那一轮有 43 条引用，初稿写了"电话会说 2027 年资本开支大幅上升"。校验报 `missing_citation`，重写后整段被删，还写上"未取到……业绩电话会的可核验原文"，实际已经取到了（[38]）。

**原因：** 重写那一步（`tool_messages(closing=True)`）不带完整的工具结果，只带最近 10 条已接受的证据，并截到 22,000 字符（`app/agent_workflow/direct.py:1258`），结果目录每组也只放 8 行。重写指令又要求"找不到来源就删掉""不要写成待核对"（`direct.py:244-253`）。触发删除的是旧的答案校验，不是还处于 shadow 的 CLAIM 闸门（`CLAIM_QUOTE_GATE`），CLAIM 保持 shadow。

**决定：**
- 校验只标注，不删内容。重写只允许修正 `[n]` 编号，改指令文案。
- 重写时要带上被拒的行所引来源的完整 `quote`，以及 `rejected_numbers_appear_in` 指向的来源。能确定的编号先用代码自动改。
- 还核对不上的句子原样保留，通过流事件和 `agent_messages.tool_calls` 带上 `unverified_lines: [{line, reason, numbers}]`，刷新后也能回放。
- 前端在这些句子上标"证据不足"并写明原因，旁边放"追问依据"按钮（把"这句话的依据是什么：<句子>"填进输入框）。在任何来源里都找不到的数字标"数字未核实"，更醒目。
- Telegram 在 `app/agent_telegram.py` 的 `chat_text` 里给这些句子加"（未核实）"。
- 顺带检查 `answer_tidy.py`、`claim_review.py` 有没有其他删句子的路径。

**测试：**
- [ ] `tests/test_agent_answer_repair.py`：`test_repair_sees_cited_source`（43 条引用，被拒的行引用 [38]，重写消息里包含 [38] 的 quote）；`test_repair_keeps_lines`（模型重写时删了句子，最终回答仍保留）；`test_unverified_lines_reported`。
- [ ] `tests/test_telegram_bridge_flow.py`：`（未核实）` 的显示。
- [ ] 新建 `frontend/src/chat-unverified.mjs` 和 `frontend/scripts/chat-unverified.test.mjs`：句子匹配和标记。

**验收：** 回放那一轮的问题，电话会那段保留并引用 [38]；核对不上的句子显示"证据不足"。

### Task 8：财报阅读器和离线盲测

**触发标准（用户定的）：** 一个懂金融的人读完这份财报，能有较大把握判断股价要涨还是要跌，才提醒，涨跌都提醒；说不准就不打扰。不是"超预期多少个百分点"这种机械门槛。

**为什么要看新指引：** Intel 的实际数字（SEC 上的两份财报新闻稿）：

| | 7 月给的 Q3 指引 | Q3 实际 | 10 月给的 Q4 指引 |
|---|---|---|---|
| 营收 | 158–168 亿美元 | 165 亿 | 150–160 亿 |
| 毛利率（non-GAAP） | 42.0% | 44.1% | 38.0% |
| 每股收益（non-GAAP） | $0.38 | $0.52 | $0.25 |

每股收益超出指引 37%，第二天却跌了 28.6%。公司常把指引说低，超指引不算新闻，市场看的是新指引：营收中值比本季低 6%，每股收益砍掉一半多，CFO 还说 PC 放缓至少持续到明年上半年。懂行的人读完应判"偏跌、把握大"。

**文件：** 新建 `app/earnings_reader.py`、`scripts/earnings_blind_test.py`、`config/blind_test_universe.txt`、`tests/test_earnings_reader.py`。修改设置页和模型目录相关文件，新增"财报判断模型"下拉。

**接口：**
```python
READER_VERSION = "earnings-reader-v1"
daily_sigma(closes, exclude_dates, n=126) -> float | None
label_reaction(r: float, sigma: float) -> Literal["up", "down", "flat"]   # 门槛 max(2*sigma, 0.03)
extract_release(text, model) -> ReleaseFacts     # 营收、毛利率、EPS、下季指引；每个数字必须能在原文找到，否则为空
compare(facts, prior_guidance, history, prices) -> Comparison   # 纯 Python
judge(facts, comparison, commentary, after_hours_return, model) -> Judgment
# Judgment: direction("up"|"down"|"unclear")、confidence("high"|"medium"|"low")、reasons[{text, quote}]、counter_argument
```

模型调用用 `app/agent_chat_provider.py` 的 `decision_request` 直接调，不走工具循环。

**"涨/跌"的规则（盲测按这个打分）：**
- 反应幅度 R = 发布后第一个交易日收盘 ÷ 发布前最后一个收盘 − 1。盘前发布的，用当天收盘对比前一天收盘。
- σ = 发布前 126 个交易日（约半年）日涨跌幅的标准差，剔除这段时间里的财报反应日。
- R ≥ +max(2σ, 3%) 算涨，R ≤ −max(2σ, 3%) 算跌，其余算没大动。平常约 95% 的交易日落在 ±2σ 内。
- 按 10-30 的行情算出的门槛：AAPL 3.3%、MSFT 4.5%、NVDA 4.9%、TSLA 6.2%、AMD 9.4%、INTC 9.8%。

**必看清单（`compare` 算好给 `judge`）：** 本季实际对比上季指引，并扣掉这家公司惯常超出的幅度；新指引对比本季实际和往年同期；管理层对后市的说法；超出部分的质量（一次性收益、税率、GAAP 和 non-GAAP 的差）；财报前股价已经涨跌了多少。

**模型可配置：** 设置页选（来自模型目录），存 `agent_model_roles(owner_hash, role, model_name)`，`role` 取 `earnings` 或 `forecast`，默认用服务器默认模型。

**盲测：**
- [ ] 财报范围：标普 100 最近两季（约 200 份）。`config/blind_test_universe.txt` 自行整理，CIK 用 SEC 的 `company_tickers.json` 映射。
- [ ] 模型可能记得出名的历史行情，所以同时跑一组把公司名、代码、日期遮掉的版本，对比差异，以遮掉的版本为准。
- [ ] 脚本可断点续跑，并发 4，把结果写成 JSONL，报告写到 `docs/reports/2026-11-earnings-blind-test.md`。
- [ ] 打分只看 `confidence=high`：判涨且实际涨、判跌且实际跌才算对，实际没大动或方向相反都算错。同时报覆盖率。按模型和 `READER_VERSION` 分别统计。
- [ ] 上线标准：高把握判断至少 20 次，命中率 ≥ 80%。没达到就如实写进报告，第二条消息只按普通通知发。

**测试**（`tests/test_earnings_reader.py`）：
- [ ] `label_reaction`：INTC 今年四次，(−0.170, 0.0385) 为 down，(+0.236, 0.0401) 为 up，(−0.079, 0.0494) 为 flat，(−0.286, 0.0490) 为 down。
- [ ] `label_reaction(-0.025, 0.005)` 为 flat（3% 下限生效）。
- [ ] `daily_sigma` 剔除指定日期；数据少于 20 天时返回 None。
- [ ] `compare`：用上表 Intel 数字，营收对中值 +1.2%，EPS 对指引 +36.8%，新指引营收中值对本季 −6.1%，EPS −51.9%，毛利率 −6.1 个百分点。
- [ ] `extract_release`：原文没有的数字被置空。

**验收：** 用 Intel 这份（accession `0000050863-26-000188`，上一季 `0000050863-26-000155`）跑 `judge`，给出 `down`、`high`，理由带原文。盲测报告出来，门槛定下来。

### Task 9：财报监控上线

**流程：**

1. **发现（哨兵）：** 监控持仓和研究队列的公司，读 `data.sec.gov/submissions/CIK##########.json`，只认 `form=8-K` 且 `items` 含 `2.02`，按 accession 去重（存 SQLite）。这个 JSON 里 `acceptanceDateTime` 的 Z 是真 UTC（苹果财报夏令时是 20:30，冬令时是 21:30）。
   - 频率：平时 30 分钟一次；财报窗口内 2 分钟一次。
   - 财报窗口：上次财报日 + 91 天，前后 10 天内的美东 06:00–09:30 和 16:00–17:30（用 `zoneinfo`，不写死时差）。
   - 总请求速率不超过每秒 5 次，带 `SEC_EDGAR_USER_AGENT`。
2. **第一条：财报分析（API）：** 收到事件后用 `fetch_inventory_content`（`app/sec_filings.py:478`，8-K 优先取 Exhibit 99.1），`extract_release` 加 `compare`，几分钟内发出：关键数字对比上季指引、新指引、管理层说法、超出部分的质量。持仓公司推送给用户；只在研究队列的公司，只在 bot 对话里留记录，不推送。发到关注这家公司的 bot 的对话，没有就发到默认 bot（`agent_tasks.post_to_line`）。
3. **第二条：追加提醒（API）：** 发布后约 30 分钟，带上盘后（或盘前）走势跑 `judge`。方向不是 `unclear` 且把握达到该模型的门槛才发：方向、把握、两三条理由、对仓位的影响、用户预设的计划、可用资金够不够。判断和盘后走势相反时，要提示有分歧。没过盲测的模型只按普通通知发，并注明"该模型未经盲测"。定时状态存库，重启后能接上。
4. **兜底（哨兵）：** 2 分钟内 API 没响应，哨兵直接发"财报已出（带 SEC 链接），分析暂时不可用"。

**历史小表：** 新表 `earnings_history`（symbol、季度、accession、发布时间、指引、实际、R、σ、判定），首次用到时回填过去 8–12 个季度。只用这份财报发布之前就有的数据。

**测试**（`tests/test_earnings_monitor.py`、`tests/test_sentinel_filings.py`）：
- [ ] `test_only_item_202_triggers`：`items=5.02` 的 8-K 不触发。
- [ ] `test_same_accession_once_across_restart`：重启哨兵后不重发。
- [ ] `test_window_uses_new_york_time`：夏令时和冬令时都落在正确的窗口内。
- [ ] `test_holding_pushes_queue_records`：持仓推送，研究队列只记录。
- [ ] `test_unclear_sends_no_followup`。
- [ ] `test_api_down_sends_fallback`。
- [ ] `test_history_excludes_future`：小表不含发布时间之后的数据。

**验收：** 回放 Intel 10-29：8-K 进 SEC 后 5 分钟内发现（之前晚 4.6 小时），第一条分析送达，第二条判"偏跌、把握高"并带出处。

### Task 10：Telegram 要有反馈

**现象：** 提问后一点动静都没有，分不清是挂了还是在想。10-31 那 6 轮每轮干等 25–106 秒；近 7 天每轮中位数 22 秒，P90 65 秒。用户发"hello ?"试探，收到的却是"超出 FinBot 功能范围"的固定回复。

**原因：** `scripts/run_telegram_bridge.py` 的 `_ask_agent`（`:297`）把整轮收完才发。主循环（`:116-157`）逐条 `await`，一轮没结束，新消息、按钮和发件箱都得等，提醒也可能被一条长回答堵住。

**决定：**
- 收到消息立刻发 `sendChatAction: typing`，每 4 秒续一次。
- 2 秒内回一条"收到，正在处理……"，之后用 `editMessageText` 按流里的步骤事件更新进度（至多每 2 秒一次），不额外调模型。最后另发一条完整回答，这样用户会收到通知。
- 每轮放后台任务，主循环继续收消息、处理按钮、发发件箱。不同 bot 可并行。同一个 bot 还在回答时，新消息排队，并马上回"收到，排在上一条后面"（服务端同一对话并发会返回 409 `conversation_busy`）。
- 问候和"在吗"这类消息，在分类器示例里归到不用工具的简短回答，不走 C 路由的固定回复。不要写正则。
- API 连不上时，桥 5 秒内回"后端暂时连不上，提醒不受影响"。

**测试**（`tests/test_telegram_bridge_flow.py`，用假的 Telegram 客户端）：
- [ ] `test_typing_and_ack_before_answer`。
- [ ] `test_progress_edits_are_throttled`。
- [ ] `test_long_turn_does_not_block_other_bot_callback_or_outbox`。
- [ ] `test_same_bot_second_message_queued`。
- [ ] `test_api_down_replies_quickly`。

**验收：** 1 秒内显示"正在输入"，2 秒内有确认语；一条长回答进行中，其他消息和提醒照常收发；"在吗"立刻回复。

### Task 11：盘中异动

规则都是跟这只股票自己的过去比，不用统一的百分比。

**文件：** 修改 `sentinel/signals.py`、`sentinel/main.py`；新建 `tests/test_sentinel_signals.py`。

**接口**（纯函数）：
```python
bucket_of(ts_et) -> Literal["pre", "open30", "mid", "close30", "post"]
short_move_signal(r, bucket_sigma) -> bool        # |r| ≥ 4×sigma 且 |r| ≥ 1%；sigma 为 None 时 5 分钟窗口用 |r| ≥ 5%
daily_move_level(r_from_prev_close, sigma) -> int # 0 无；超过 2σ 为 1；超过 3σ 为 2；sigma 为 None 时 |r| ≥ 8% 为 1
gap_signal(price, prev_close, sigma) -> bool      # 开盘价或盘前价相对昨收超过 2σ
is_stale(last_bar_ts, now) -> bool                # 最新 K 线超过 10 分钟
```

**决定：**
- 数据：Yahoo chart（`app/market_data.py:14` 同一个接口），`interval=1m&includePrePost=true`，交易时段（美东 04:00–20:00）每分钟拉一次持仓和研究队列；基线用 `interval=5m`（能取最近 60 天），过去 20 个交易日按时段算 σ，存 SQLite，每天更新一次。
- 短时急涨急跌看 5 分钟和 15 分钟两个窗口。
- 放量只作佐证：5 分钟成交量超过同时段 20 天平均的 5 倍时标"放量"，单独不触发。
- 持仓全部按上面的规则提醒，涨跌都提醒，只有跌会升级。提醒里写清亏了多少钱、占总资产几成。预设计划的补仓价、止损价、目标价被穿过时也提醒。
- 研究队列只在当天累计 level 2（超过 3σ）时发普通通知，不升级。INTC 的 3σ 约 14.7%，10-30 那次会触发。
- 同一只股票、同一种信号，30 分钟内只提醒一次，除非又多走了 1σ。
- 财报提醒未确认、开盘又急跌，直接升级。
- 最近 2 天有拆股事件（Yahoo `events=splits`）时跳过信号，并提醒用户核对持仓。

**测试**（`tests/test_sentinel_signals.py`）：
- [ ] `gap_signal(68.36, 92.07, 0.0490)` 为真；`daily_move_level(-0.2575, 0.0490) == 2`。
- [ ] AAPL（σ=0.0164）：−2% 为 0，−3.4% 为 1，−5% 为 2。
- [ ] `short_move_signal(-0.05, 0.01)` 为真；`(-0.009, 0.001)` 为假（1% 下限）；`(-0.05, None)` 为真；`(-0.03, None)` 为假。
- [ ] `bucket_of`：美东 09:35 是 `open30`，12:00 是 `mid`，夏令时和冬令时都对。
- [ ] `test_stale_or_empty_bars_no_signal`：空值、停牌、休市不出信号。
- [ ] `test_split_no_false_alarm`：1 拆 10 不触发急跌。
- [ ] `test_cooldown_and_deepening`：30 分钟内不重复，又走 1σ 才再提醒。

**验收：** 模拟 5 分钟跌 5%，1–2 分钟内收到提醒，带对仓位的影响。

### Task 12：升级提醒

**决定：**
- Telegram 提醒带「收到」按钮；用户点按钮或回复这条消息，都算确认。桥把确认写进 `data/sentinel.db`（WAL 模式）。
- 白天 1 分钟没确认，升级为 Pushover 紧急级（`priority=2, retry=60, expire=1800`，每分钟响一次直到确认，30 分钟后停）。在 Pushover 里确认也算确认（轮询 receipt）。
- 夜间是北京时间 0–8 点。夜里只有两种情况直接响铃：持仓公司财报追加提醒判为"偏跌、把握高"；持仓股急跌且占总仓位 ≥ 10%。其他提醒早上 8 点汇总发。
- 没配 Pushover 时，改为 Telegram 每 5 分钟重发一次，最多 3 次。
- 提醒类消息不占 bot 的 `daily_notify_cap`。
- 设置页加 Pushover 的 user key 和 app token，API 存进加密凭证（`secret_box`），并写入 `sentinel-config.json`。
- **打电话这周不做**（Twilio 打国内手机容易被拦，国内语音通知一般要企业资质）。

**测试**（`tests/test_sentinel_escalation.py`，用假的 Pushover）：
- [ ] `test_day_escalates_after_one_minute`、`test_ack_stops_escalation`。
- [ ] `test_night_rules`：判偏跌且把握高时响铃，其他留到 8 点汇总；0:00 和 8:00 的边界正确。
- [ ] `test_no_pushover_falls_back_to_telegram`。
- [ ] `test_alerts_ignore_daily_cap`。

**验收：** 不点「收到」，1 分钟后手机响；点了就停。

### Task 13：工具渐进披露

**现状：** 所有者每轮默认带 36 个工具的完整定义，约 30 KB（8–10k token）；`app/agent_context.py` 的 `FIXED_TOKENS=8000` 光工具就快用完了。工具目录共 61 个。用户还计划把系统里能点的操作都做成工具。

**做法：** 照技能的方式（`app/agent_skills.py`：提示词只放名字和一句话，要用时调 `use_skill`）。

**文件：** 修改 `app/agent_tool_catalog.py`（`schemas`，`:309`）、`app/agent_workflow/direct.py`、`app/agent_context.py`、`frontend/src/agent-tool-labels.mjs`；新建 `tests/test_tool_disclosure.py`。

**接口：**
```python
TOOL_CATEGORIES: dict[str, CategoryInfo]   # 名字、一句话说明、工具列表
ALWAYS_ON: frozenset[str]
load_tools(categories: list[str])          # 新工具；结果返回后，下一次模型调用带上这些定义
```

**分类：**

| 分类 | 工具 |
|---|---|
| 常驻 | `ask_user`、`use_result_set`、`calculate`、`calculate_formula`、`read_history_citation`、`request_action`、`use_skill`、`load_tools` |
| 行情 | `query_stock_prices`、`initialize_prices` |
| 财报与 SEC | `query_sec_filings`、`query_financials`、`review_filing`、`fetch_sec`、`refresh_sec`、`scan_official` |
| 资料库 | `query_materials`、`query_material_analysis`、`search_material_analysis`、`search_knowledge`、`save_material_evidence`、`ingest_web_source`、`import`、`import_sources`、`index`、`retry_document_index`、`withdraw_knowledge_document`、`review_knowledge_candidate`、`analyze`、`translate_content`、`test_retrieval_diagnostics` |
| 新闻与网页 | `web_research`、`search_configured_news`、`list_news_sources`、`dry_run_news_source`、`diagnose_news_source`、`upsert_news_source`、`disable_news_source`、`set_news_source_alternate`、`repair_news_source_with_rea` |
| 预测 | `query_latest_forecast`、`forecast`、`revise_forecast`、`start_historical_replay` |
| 持仓 | `query_portfolio`、`record_trade`、`set_available_funds`、`set_position_plan` |
| 例行与通知 | `create_routine`、`list_routines`、`update_routine`、`delete_routine`、`notify_telegram` |
| 记忆与技能 | `remember`、`forget`、`recall_conversations`、`read_past_conversation`、`save_skill` |
| 工作区 | `read_workspace`、`query_system_status`、`query_research_queue`、`add_to_research_queue`、`remove_from_research_queue`、`query_research_faq`、`select_stock`、`open_page` |

**决定：**
- 按意图预加载：根据分类器的 `scope`、`tool_bias`、`requested_actions`，以及上一轮用过的分类，直接带上相应定义，大部分轮次不用多走一步。
- 结果要和 bot 的 `tool_scope`、技能的 `allowed_tools` 取交集。"看得见"不等于"能执行"，确认卡不变。
- 工具定义的顺序保持稳定，少破坏模型服务商的前缀缓存。
- 把 7 个新闻源管理工具并成一两个带 `action` 参数的。
- `FIXED_TOKENS` 改成按实测的系统提示和工具大小计算。

**测试：**
- [ ] `test_every_tool_has_category`：目录里每个工具都有且只有一个分类。
- [ ] `test_default_payload_under_8kb`：默认一轮的工具定义 ≤ 8 KB。
- [ ] `test_load_tools_adds_schemas_next_call`。
- [ ] `test_load_cannot_exceed_bot_scope`：范围外的工具加载不到。
- [ ] `test_writes_still_need_card`。

**验收：** 每轮工具定义从约 30 KB 降到 8 KB 以内；现有 50 条行为测试（见 `docs/reports/agent-routing-verification.md`）通过率不下降；统计多出来的往返次数。

### Task 14：预测改用推理模型

**现状：** 预测用 OpenRouter Decisions 接口的 `typesafe/jev-1.13`（`app/jev_provider.py`），只会三选一（20 个交易日，±2%）。已到期的 10 次预测：方向对 60%，Brier 0.787，Log loss 1.317，都差于"三种结果各猜三分之一"的基线（0.667、1.099）。校准器一个都没启用。样本少且集中在 9 月底，不能下定论，但看不出它有判断能力。

**文件：** 新建 `app/forecast_model_provider.py`、`tests/test_forecast_model_provider.py`。修改 `app/agent_forecast_processor.py`、`app/forecast_v2_processor.py`、`app/forecast_v2_api.py`、设置页（"预测模型"下拉，`role=forecast`）、`frontend/src/App.tsx`（到期评估页）。

**决定：**
- 返回形状和 `jev_provider` 相同（三类概率），`model_status=experimental_llm`，`question_version=llm-direction-v1`，判断标准不变。到期评估和校准照常能用。
- 每次预测同时问一次 Jev 做对照：写成隐藏的对照预测，不出现在预测列表，但进入到期评估。两组在评估页分开显示。Jev 失败不影响主预测。
- 只换预测。`jev_memory_gate.py`、`agent_profile_extract.py`、`jev_claim_support.py` 这些快速三选一的小场景继续用 Jev。

**测试：**
- [ ] `test_probabilities_normalized`：概率和不为 1 时被拒。
- [ ] `test_control_failure_does_not_fail_primary`。
- [ ] `test_control_hidden_from_list_but_in_cohorts`。
- [ ] `test_model_role_setting_used`。

**验收：** 新预测由配置的模型给出，到期评估页两组分开显示。

### Task 15：上下文和 AI 压缩

**现状：** 历史预算默认 64 KB，上限 128 KB，而默认窗口 128k token，只用了约六分之一。主 FinBot 对话 524 条消息，更早的内容只剩 7 段摘要，共 1962 字；每次只带最新 5 段，每段最多 400 字，提示词还不许写数字和结论（`app/agent_context_summary.py:31`）。第二层是机械截断：原话留 1000 字，回答留开头 160 字。上下文表一直停在 90% 以上，用户以为没在压缩，也没有手动入口。每个 bot 只有一条永远不结束的对话，所以问题被放大了。

**参考 Grok Bot：** 压缩管近期工作，按占窗口的比例触发，成批压旧消息，可多次压；记忆条目管长期事实，和对话分开。FinBot 已有后者（画像），前者太薄。

**文件：** 修改 `app/agent_context.py`、`app/agent_context_summary.py`、`app/agent_chat_models.py`、`app/agent_recall.py`、`frontend/src/AgentChatPanel.tsx`、`frontend/src/ContextMeter.tsx`、`frontend/src/context-usage.mjs`；新建 `tests/test_context_rolling_summary.py`。

**决定：**
- 预算跟着所选模型的窗口走（模型目录没有窗口字段就加一个，默认 128k）：历史预算 = 窗口的 50%，再按 `BYTES_PER_TOKEN` 换算。去掉 128 KB 的上限。
- 由模型做 AI 压缩，用一份结构化滚动摘要：目标、结论和出处、没办完的事、偏好、关键数字。每次把旧摘要和刚被挤出去的几轮合并成新版，不是追加新段、丢掉旧段。
- 摘要可以写数字和结论，但每条标明 `{turn_id, ordinal}`，需要时用 `read_history_citation` 取回原文。摘要只算记忆，不算证据。
- 历史用量到预算的 80% 时自动压缩，在后台跑，不拖慢回答。
- 输入 `/压缩`（可带重点，如"/压缩 重点保留 Intel 的分析"）或点上下文卡片的按钮，都能手动触发，网页和 Telegram 都支持。
- 压缩时在对话里插一条"已压缩 N 轮"，点开能看摘要。
- 机械截断的第二层先留着，摘要稳定后再去。
- `recall_conversations` 扩展到能搜同一个 bot 的对话，摘要里没有的细节可以查回来。

**测试：**
- [ ] `test_merge_keeps_old_facts`：合并后旧摘要里的结论还在。
- [ ] `test_numbers_carry_source`：没有来源标记的数字被拒。
- [ ] `test_model_failure_keeps_old_summary`：模型失败时旧摘要不丢。
- [ ] `test_auto_trigger_at_80_percent`、`test_manual_compact_with_focus`。
- [ ] `test_budget_follows_window`：128k 和 1M 窗口算出不同预算。
- [ ] `frontend/scripts/context-usage.test.mjs` 更新。

**验收：** 主 FinBot 对话里早期说过的事能答出来或查回来；`/压缩` 能用，压缩时对话里有提示。

### Task 16：README 和前后数据

- [ ] `README.md`、`README.en.md` 改成个人金融助手的定位，补上多 bot、例行任务、Telegram、持仓、监控，并更新架构和发布记录。
- [ ] 写 `docs/reports/2026-11-personal-finance-before-after.md`：第八节每一项填上改之后的实测值。
- [ ] 全量回归：CI 全绿；冒烟：访客提问、所有者提问、持仓、Telegram、财报回放。

---

## 八、改之前的基线（2026-11-01 实测）

| 指标 | 改之前 |
|---|---|
| 财报发现延迟 | Intel 8-K 晚 4.6 小时，原文没拉，没有提醒 |
| SEC 监控停摆 | 连续 6 晚每晚停 10–16 小时 |
| Telegram 首次反馈 | 每轮干等 25–106 秒（10-31 的 6 轮） |
| 每轮回答耗时 | 近 7 天中位数 22 秒，P90 65 秒，最长 152 秒（145 轮） |
| 每轮工具定义 | 36 个，约 30 KB |
| 长对话记忆 | 524 条消息只剩 7 段摘要，共 1962 字 |
| 预测成绩（Jev） | 10 次到期，方向 60%，Brier 0.787，Log loss 1.317（均匀猜基线 0.667、1.099） |
| 技能存库 | 两次都因措辞被拒（`not_asked`） |

## 九、用户要做的事

- 今晚合上 Mac 跑过夜心跳（Task 0）。
- 注册 Supabase 并建项目；注册一个外部心跳监控服务。
- 把 `.env`、`data/personal-chat-login.json` 安全地传到 Muse。Muse 上需要的环境变量：`DATABASE_URL`、`APP_API_ACCESS_KEY`、`DEEPSEEK_API_KEY`、`OPENROUTER_API_KEY`、`TAVILY_API_KEY`、`SEC_EDGAR_USER_AGENT`、`FORECAST_DECISION_MODE`、`PUBLIC_API_MODE`、`CORS_ALLOWED_ORIGINS`、`CLAIM_QUOTE_GATE`、`CLAIM_JEV_SUPPORT`、`CLAIM_JEV_DAILY_CAP`，以及本计划新增的 `RAG_REMOTE_URL`、`SENTINEL_TOKEN`、`SENTINEL_HEARTBEAT_URL`、`BACKGROUND_LOOPS`、`DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_CONNECT_TIMEOUT`。
- 做 Task 4 里标"Mac"的步骤（可以交给 Mac 上的 Claude Code）。向量库和模型（`data/knowledge`，4.5 GB）留在 Mac，不用搬。
- 注册 Pushover 并购买（一次性约 5 美元），把 key 填进设置页。
