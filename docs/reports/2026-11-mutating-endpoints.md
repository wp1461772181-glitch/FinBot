# 会改数据的接口 vs. 助手的 `act`：哪些事能点按钮、不能开口说

日期：2026-11-24　范围：`app/` 下全部 `POST/PUT/PATCH/DELETE` 路由；`app/kernel/act.py` 的 `OPERATIONS`；生产盒最近 30 天的对话。只读调研，未改代码。

## 结论（先看这里）

- `app/` 里一共 **92** 条会写数据的路由（91 条 `@router/@app` 装饰器 + `local_model_profiles` 的一条 `PUT`；`inbox/confirm` 一个处理函数挂了 3 个路径，另有 `main.py` 里的一份拷贝，都按路由单独计数）。
- 分类：**已覆盖 27 条**（有对应的 `act` 操作）、**刻意不开放 49 条**、**缺口 16 条**。
- 缺口集中在六件事：给 bot 本身做管理、例行任务的"每隔 N 小时"类参数、AI 分析指定模型、技能的启停/改/删、持仓记错后删一笔、新闻源和通知渠道的配置。其中真正在对话里被提过、助手当场答不了的只有 **3 件**（见第二节）；其余缺口在最近 30 天没有任何对话证据，只是"页面上能点、聊天里不能说"。
- "已覆盖"里有两处只覆盖了一部分参数（例行任务调度、上传材料只收文字），这两处的缺口比列表上显示的大。
- 值得先看的异常：`POST /finbot/routines/{id}/confirm` 没有 owner 校验也不强制 token，且与另外三条路径是同一个功能的重复实现；详见第四节。

### 数据口径（生产盒，最近 30 天）

- 用户消息 932 条，其中 919 条来自 owner 的 bot 对话线，另 13 条不在任何 bot 线里；共 435 个对话。
- 要剔除两类噪声：系统自动贴入的"定时任务 / 例行任务结果"（不是 owner 说的），和 11-11、11-13、11-15 几个时段里在几十个对话里原样重复的问题（脚本化回放，不是真实需求）。剔除后真实请求大约几百条，多数是查数据、查财报、对比公司，属于读操作，`act` 不涉及。
- 助手遇到"做不到"的回复，我用关键词（没有工具/无法创建/不能修改……）扫了一遍全部助手消息，再逐条人工核对；工具返回的错误码也统计过（`write_tool_not_granted` 4 次、`not_asked` 2 次，都是 11-01 之前旧流程的授权问题，其中入库和新增技能这两类如今已有对应的 `act` 操作）。
- 近 30 天里 `act` 对应的卡片实际使用情况（来自 `agent_consents`，按操作名统计，含尚未处理或取消的卡片）：`ingest_web_source` 12、`fetch_sec` 6、`create_routine` 3、`initialize_prices` 5、`add_to_research_queue` 4、`analyze` 2、`delete_routine` 2、`update_routine` 1、`save_skill` 1、`record_trade` 1、`remember` 2、`set_available_funds` 1（取消）。也就是说 `act` 已经覆盖了 owner 实际在做的大部分写操作。

---

## 一、全部路由清单

标记：**已覆盖**（括号里是 `act` 操作）、**刻意不开放**（写明理由）、**缺口**（写明 owner 会怎么说）。路径里 `/agent-chat` 前缀省略处已在标题注明。"刻意不开放"里，凡是代码或项目规则里没有明文规定、是我按性质判断的，在理由里写了"（判断）"。

### 1. 对话与登录（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/stream` | 跑一个对话回合（助手本身） | 刻意不开放 | 它就是助手，不是助手要操作的对象 |
| POST `/hello` | 用调用方给的模型和 key 试一句话 | 刻意不开放 | 只读的连通测试，游客可用，不改数据 |
| POST `/messages` | 不带工具地直连模型聊天 | 刻意不开放 | 游客直连通道，无工具，不改 owner 数据 |
| POST `/models` | 列出服务商可用模型 | 刻意不开放 | 只读，要调用方的 key |
| POST `/conversations/{id}/cancel` | 停止正在跑的回合 | 刻意不开放 | 停止按钮；回合在跑的时候助手本身无法响应 |
| POST `/conversations/{id}/compact` | 压缩对话上下文 | 刻意不开放 | 已有「/压缩」命令，属于对话控制（判断） |
| POST `/bots/{id}/compact` | 同上，按 bot 找对话线 | 刻意不开放 | 同上（Telegram 用） |
| PATCH `/conversations/{id}` | 对话改名、归档/恢复 | **缺口** | "把这个对话命名为……""归档这条"；无对话证据，价值低 |
| POST `/personal-login` | 用口令换 owner 凭据 | 刻意不开放 | 登录；凭据不经过助手 |

### 2. Bot 管理（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/bots/{id}/read` | 标记 bot 的简报已读 | 刻意不开放 | 打开页面时的界面状态（判断） |
| POST `/bots` | 新建 bot（名称、模型、关注公司、工具范围…） | **缺口** | "帮我新增一个 Bot"；**有对话证据**（见第二节 G3） |
| PATCH `/bots/{id}` | 改 bot 的名称、关注、模型、工具范围、置顶、隐藏等 | **缺口** | "把这个 bot 换成 xx 模型""只让它看半导体" |
| DELETE `/bots/{id}` | 删除 bot（带走它的对话线） | **缺口** | "删掉这个 bot"。风险大、不可逆，若开放应放最高档卡片；我倾向保持手动，但它不是已有的明文决定 |

### 3. 模型目录与角色（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/model-catalog` | 添加模型条目（可带 API key） | 刻意不开放 | 带密钥；密钥只由 owner 在页面里放 |
| POST `/model-catalog/test` | 用某条目的 key 试连通 | 刻意不开放 | 只读测试，用到 key |
| POST `/model-catalog/models` | 列服务商模型 | 刻意不开放 | 只读，用到 key |
| PATCH `/model-catalog/{name}` | 改条目、换 key、重命名 | 刻意不开放 | 带密钥 |
| DELETE `/model-catalog/{name}` | 删条目（被占用时拒绝） | 刻意不开放 | 会带走已存的 key（判断） |
| PUT `/model-catalog/default` | 设默认对话模型 | **缺口** | "把默认模型换成 xx"；无 key，可走卡片 |
| PUT `/model-roles/{role}` | 指定某个后台任务（财报判断、预测、分析…）用哪个模型 | **缺口** | "财报判断改用 xx 模型"；与 G2 同属"选模型" |

### 4. 技能（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/skills` | 新建技能 | 已覆盖（`save_skill`） | 卡片上可选"保存并启用"或"存为草稿" |
| PATCH `/skills/{id}` | 改技能内容 | **缺口** | "把异动归因那个技能加一步……"；现在只能新存一份 |
| POST `/skills/{id}/enabled` | 启用/停用技能 | **缺口** | "先停用这个技能" |
| POST `/skills/{id}/copy` | 复制技能 | 刻意不开放 | 界面便利；用 `save_skill` 可达到同样结果（判断） |
| DELETE `/skills/{id}` | 删除技能 | **缺口** | "删掉那个旧技能" |
| POST `/skills/import/preview` | 预览一份 markdown 技能文件 | 刻意不开放 | 只读预览 |
| POST `/skills/import` | 导入 markdown 技能文件 | 已覆盖（`save_skill`，等效） | owner 把 markdown 贴进对话即可 |

### 5. 画像与记忆（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/profile` | 手动加一条记忆 | 已覆盖（`remember`） | 要带 owner 本轮原话作引文 |
| PATCH `/profile/{id}` | 改一条的文字、移到别的 bot 层 | **缺口** | "把第 3 条改成……""这条只在某 bot 里用"；`forget`+`remember` 可绕过，价值低 |
| POST `/profile/{id}/confirm` | 把"推断项"确认为"明示" | 刻意不开放 | 确认推断本来就是 owner 亲手点一下的动作；让模型代点会使这个区分失去意义（判断） |
| DELETE `/profile/{id}` | 删除（归档）一条 | 已覆盖（`forget`） | |

### 6. 研究队列与例行任务（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| PUT `/research-queue` | 整体替换研究队列 | 已覆盖（`add_to_research_queue` / `remove_from_research_queue`） | 增删各一条，立即生效（档 1） |
| POST `/tasks` | 新建例行任务 | 已覆盖（`create_routine`） | **只覆盖部分参数**：只有 hourly/daily/weekdays；接口还有「每 N 小时/天/周」、最多运行次数、通知渠道、简报或告警类型、技能 |
| PATCH `/tasks/{id}` | 改/暂停/恢复任务 | 已覆盖（`update_routine`） | 同上，参数缺口见第二节 G1 |
| DELETE `/tasks/{id}` | 删除任务 | 已覆盖（`delete_routine`） | |

### 7. 收件箱与确认（前缀 `/agent-chat`，`main.py` 那条无前缀）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/inbox/{id}/status` | 把简报标为已读/完成/忽略 | 刻意不开放 | 界面状态（判断） |
| POST `/inbox/{id}/card` | 把"待你确认"建议在原对话里生成确认卡 | 刻意不开放 | 系统机制，把建议变成卡，本身不是 owner 的意图 |
| POST `/inbox/{id}/confirm` | 点确认/跳过/稍后 | 刻意不开放 | 这是 owner 自己的同意动作，不能由助手代点 |
| POST `/routines/{id}/confirm` | 同一个处理函数的另一个路径 | 刻意不开放 | 同上；**重复路径** |
| POST `/routines/confirmations/{id}/action` | 同一个处理函数的第三个路径 | 刻意不开放 | 同上；**重复路径** |
| POST `/finbot/routines/{id}/confirm`（`main.py`） | 同一功能的第二份实现，通知里直接点 | 刻意不开放 | 同上；**无 owner 校验，见第四节** |

### 8. 新闻源（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| PUT `/news-sources/push-settings` | 推送摘要的字数上限 | **缺口** | "推送摘要短一点"；无对话证据，价值很低 |
| POST `/news-sources` | 新增/更新一个新闻源（RSS 或网页地址） | **缺口** | "加一个 xx 的 RSS 源"；写入的是一个网址，应放确认卡并展示试跑结果 |
| POST `/news-sources/{id}/enabled` | 启用/停用新闻源 | **缺口** | "先把某个源停掉" |
| POST `/news-sources/{id}/dry-run` | 试抓一页，不写配置 | 刻意不开放 | 只读试跑，不改配置 |
| POST `/news-sources/{id}/repair` | 让 REA 自动修一个坏掉的源 | 刻意不开放 | 维护类动作，有每小时一次的冷却；见第四节 |
| DELETE `/news-sources/{id}` | 删除新闻源 | **缺口** | "把某个源删了" |

### 9. 后台模型、通知渠道、Telegram、Pushover（前缀 `/agent-chat`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| PUT `/background-model` | 设置后台任务用的模型，可带 key | 刻意不开放 | 带密钥 |
| DELETE `/background-model/key` | 清除已存的后台 key | 刻意不开放 | 密钥管理 |
| PUT `/channels` | 主动消息走哪些渠道（站内/Telegram/微信）与模式 | **缺口** | "别再用 Telegram 推我了""改成只站内"；不含密钥，可走卡片 |
| POST `/telegram/token` | 保存共用 Telegram bot 的 token | 刻意不开放 | 凭据 |
| POST `/telegram/bind` | 生成一次性绑定码 | 刻意不开放 | 绑定渠道要 owner 自己用手机发码 |
| POST `/telegram/unbind` | 解绑 | 刻意不开放 | 渠道绑定管理 |
| PUT `/pushover` | 保存 Pushover 的 user key 与 app token | 刻意不开放 | 凭据 |
| DELETE `/pushover` | 清除 Pushover 凭据 | 刻意不开放 | 凭据 |
| POST `/bots/{id}/telegram/token` | 保存某 bot 自己的 Telegram token | 刻意不开放 | 凭据 |
| POST `/bots/{id}/telegram/bind` | 某 bot 的一次性绑定码 | 刻意不开放 | 绑定渠道 |
| POST `/bots/{id}/telegram/unbind` | 解绑 | 刻意不开放 | 渠道绑定管理 |
| DELETE `/bots/{id}/telegram` | 删除某 bot 的 token | 刻意不开放 | 凭据 |

微信：`app/` 里没有任何微信的写接口。绑定与登录令牌由微信桥进程自己处理，`/channels` 只把 `wechat` 列为可选渠道。所以微信没有"页面能点而助手不能"的对应物。

### 10. 持仓（前缀 `/agent-chat/portfolio`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/transactions` | 记一笔买入/卖出/分红/拆股 | 已覆盖（`record_trade`） | 只是记账，不下单 |
| DELETE `/transactions/{id}` | 删除一笔记录 | **缺口** | "刚才那笔记错了，删掉"；记账能在对话里做、改错却要去页面，是最自然的对称缺口 |
| PUT `/plans/{symbol}` | 保存某只持仓的计划/止损/目标价 | 已覆盖（`set_position_plan`） | |
| PUT `/cash` | 设可用资金 | 已覆盖（`set_available_funds`） | |

### 11. 预测

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/v2/forecast-jobs` | 排队一次新预测 | 已覆盖（`forecast`） | |
| POST `/v2/historical-replays` | 排队一次历史回放 | 已覆盖（`start_historical_replay`） | |
| POST `/v2/forecast-versions/{id}/revision-jobs` | 用材料修订一版预测 | 已覆盖（`revise_forecast`） | 材料只由 owner 在卡片上勾选，模型不选 |
| POST `/forecasts` | 写一条 mock 预测到旧表 | 刻意不开放 | 遗留的 Week 1 假数据接口 |
| POST `/forecast-runs` | 旧的离线数值预测 | 刻意不开放 | 遗留实验路径，已被 v2 取代 |
| POST `/research-runs` | 旧研究工作流 | 刻意不开放 | 遗留 |
| POST `/forecast-refresh-runs` | 旧滚动刷新 | 刻意不开放 | 遗留 |
| POST `/evidence-revisions/{symbol}` | 旧版证据修订 | 刻意不开放 | 遗留，已被 `revise_forecast` 取代 |

### 12. 资料、SEC、行情、分析、翻译

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/filing-inventories/{symbol}/scan` | 扫描 SEC 官方申报目录 | 已覆盖（`scan_official`） | |
| POST `/filing-inventories/{symbol}/{acc}/fetch` | 拉取/刷新一份申报原文 | 已覆盖（`fetch_sec` / `refresh_sec`） | |
| POST `/filing-inventories/{symbol}/{acc}/review` | 标记申报相关/不相关 | 已覆盖（`review_filing`） | |
| POST `/market-data/{symbol}/initialize` | 拉一年日线 | 已覆盖（`initialize_prices`） | |
| POST `/uploaded-evidence/{symbol}` | 上传一份材料（文件） | 已覆盖（`save_material_evidence`、`ingest_web_source`） | 只覆盖文字和网页；二进制文件/图片没法在对话里"上传" |
| POST `/v3/materials/{type}/{id}/analysis-jobs` | 对一份材料做 AI 分析 | 已覆盖（`analyze`） | **只覆盖部分参数**：接口可指定目录里的模型（`catalog_model`）和强制重跑（`force`），`act` 没有；见第二节 G2 |
| PUT `/v3/materials/analysis-settings` | 设置分析用的模型（可带 key） | 刻意不开放 | 带密钥 |
| DELETE `/v3/materials/analysis-settings` | 清除分析模型设置 | 刻意不开放 | 同一套密钥配置的重置 |
| POST `/v3/material-analyses/{id}/localization` | 把分析译成英文 | 已覆盖（`translate_content`） | |
| POST `/v2/forecast-versions/{id}/brief-localization` | 把预测简报译成英文 | 已覆盖（`translate_content`） | |

### 13. 知识库（前缀 `/knowledge`）

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/retrieval-test` | 做一次检索测试 | 刻意不开放 | 只读诊断；已有读取类工具承担 |
| POST `/import` | 把已存来源导入知识库 | 已覆盖（`import` / `import_sources`） | |
| POST `/index` | 为待处理文档建向量索引 | 已覆盖（`index`） | |
| POST `/documents/{id}/withdraw` | 把文档从检索中撤回 | 已覆盖（`withdraw_knowledge_document`） | |
| POST `/documents/{id}/retry` | 重试失败文档的索引 | 已覆盖（`retry_document_index`） | |
| POST `/candidates/{id}/review` | 通过/拒绝一条知识候选 | 已覆盖（`review_knowledge_candidate`） | |

### 14. 公开标记、哨兵、本机配置

| 方法 路径 | 改什么 | 结论 | 说明 |
|---|---|---|---|
| POST `/agent-chat/public-marks/review` | 人工复核一个已展示的标记；"确认标错"会计入熔断 | 刻意不开放 | 人工复核本身必须是人的判断，不能由模型代做 |
| POST `/agent-chat/public-marks/pause` | 手动暂停标记展示 | 刻意不开放 | 安全熔断开关，操作员动作 |
| POST `/agent-chat/public-marks/resume` | 恢复展示，要回放引用和备注 | 刻意不开放 | 恢复需要人亲自给出回放引用 |
| POST `/agent-chat/internal/sentinel/events` | 哨兵上报"财报检出/告警已发" | 刻意不开放 | 机器接口，只收回环地址 + 密令，不是用户操作 |
| PUT `/agent-chat/local-model-profiles` | 写本机模型配置文件 | 刻意不开放 | 只在本机开发模式开启，公开模式下直接 404 |

---

## 二、缺口排名（按"对话里被提过"的证据排序）

先说明证据尺度：下面凡写"有证据"，都是 owner 自己在最近 30 天对话里说过的、助手当场没做成的话；"无证据"指 30 天内没有任何对话碰到这件事。owner 的原话只引与需求相关的短句。

### 有证据的缺口

**G1　例行任务的调度参数（`create_routine` / `update_routine` 已覆盖，但参数不够）**
- 证据：10-29，owner 说「这个例行任务改成每两小时触发一次」，助手答"每两小时这一档系统不支持"。现有 `act` 参数只有 hourly/daily/weekdays，而 `POST/PATCH /tasks` 本来就支持 `every_value`+`every_unit`（小时/天/周）、`max_runs`、`channel`（站内/Telegram）、任务类型（简报/告警）、`skill_id`。
- 另外：近 30 天里 owner 对例行任务有 3 次新建、2 次删除、1 次修改的卡片；这是他在对话里用得最多的"管理类"写操作，所以参数缺口最容易再次撞到。
- 为什么不是补丁：这不是新增规则，是把已有写路径本来就接受的字段放进 `act` 的参数里。

**G2　AI 分析指定模型（`analyze` 已覆盖，但无法指定模型）**
- 证据：10-30，owner 先说「那你用后台的dots模型做一下AI分析吧」，分析却是用默认的 deepseek-flash 跑的；他追问原因，助手承认工具里没有模型选项，owner 自己总结成"只能用默认的模型"。这是这 30 天里唯一一次因为参数缺失、助手答"我做不到"的 AI 分析请求。
- 接口 `POST /v3/materials/.../analysis-jobs` 支持 `catalog_model`（用目录里的模型，key 不出现在页面）和 `force`（重跑）；`act.analyze` 两个都没有。
- 附带的读侧缺口（不是写操作，但同一场对话里暴露）：助手读不到"可选模型清单"和"当前默认模型"，所以连"现在可以选哪些"都答不上。

**G3　新增/修改 bot（`POST /bots`、`PATCH /bots/{id}`）**
- 证据：10-30，owner 问「你可以帮我新增一个 Bot 吗？」，助手答没有这项操作，让他去产品里的 bot 管理入口。生产库里 `agent_bots` 现有 6 个，创建时间在 10-28 到 11-16 之间，都是他在页面里建的，所以这是他真实会做的事。
- 只有一次对话证据，但这是三个有证据缺口里"助手答得最干脆、owner 最直接提出请求"的一个。`DELETE /bots/{id}` 不建议随之开放（带走整条对话线，不可逆）。

### 无证据的缺口（按价值估计，排在后面）

| 排名 | 缺口 | 对应路由 | 理由 |
|---|---|---|---|
| 4 | 持仓删一笔记错的交易 | `DELETE /portfolio/transactions/{id}` | 11-24 起 owner 开始在对话里记账（`record_trade` 已有 1 张卡），记错后的撤销自然是下一个需求；`record_trade` 的工具说明还写着"用户可以在持仓页删除"，说明当前是有意把撤销放到页面，但这条没有明文规则 |
| 5 | 技能的启停/改/删 | `PATCH`、`POST /enabled`、`DELETE /skills/{id}` | owner 在 11-01~11-04 集中用过技能（让助手起草、保存并启用、回看内容），技能总数 4 个；目前只能新增，改和停要去页面 |
| 6 | 选默认模型、给后台角色选模型 | `PUT /model-catalog/default`、`PUT /model-roles/{role}` | owner 对用哪个模型有明确偏好（G2 的 dots）；不含密钥，可走卡片。但无直接请求 |
| 7 | 新闻源增删启停 | `POST /news-sources`、`/enabled`、`DELETE`，`PUT /push-settings` | owner 读过自配新闻源（10-29「去今十数据看看特斯拉的新闻」），但没有要求改它；新增需要写入一个网址，有被网页内容诱导的风险，必须放确认卡 |
| 8 | 通知渠道偏好 | `PUT /channels` | owner 多次让例行任务"通过 Telegram 通知"，但那是任务指令里写的，不是渠道偏好；库里 `agent_channel_prefs` 为 0 行，说明他没改过 |
| 9 | 记忆文字编辑、对话改名归档、bot 删除 | `PATCH /profile/{id}`、`PATCH /conversations/{id}`、`DELETE /bots/{id}` | 都有绕行办法或风险大于收益 |

---

## 三、建议先加进 `act` 的东西（最多五项）

1. **扩展 `create_routine` / `update_routine` 的参数**（档 2，沿用现有卡片）：加 `every_value`+`every_unit`、`max_runs`、`channel`。理由：G1，撞到过一次；写路径本来就接受这些字段；不新增操作。
2. **给 `analyze` 加可选的 `catalog_model`（和 `force`）**（档 3，已是付费卡）：理由：G2；卡片的"代价"那一行要写明用的是哪个模型。模型名要从目录里选，同时要让助手能读到可选模型清单。
3. **新增 `create_bot` / `update_bot`**（档 2；`update_bot` 改工具范围或模型时在卡片上写明）：理由：G3；不含删除。
4. **新增 `delete_transaction`**（档 2）：理由：对称于 `record_trade`，撤销记错的账；卡片要显示被删记录的日期、标的、数量，以及删除后对成本和资金的影响。
5. **新增 `manage_skill`（启用/停用/删除/编辑）**（档 2；删除这一项可以单独成卡）：理由：`save_skill` 只能增，owner 用过技能；放在最后因为只有间接证据。

不建议现在做：模型目录和 key（密钥规则）、渠道绑定与 Telegram/Pushover（凭据规则）、`public-marks`（人工复核）、新闻源增删（先观察是否有人开口要）。

---

## 四、意外发现

1. **`POST /finbot/routines/{id}/confirm`（`app/main.py:287`）没有 owner 校验，且 token 不是必填。** 它调用的是和 `agent-chat` 下三条确认路径同一个 `handle_inline_confirmation_action`，但那三条先过 `_owner_only`，这一条直接从请求体里取 `owner_hash`（可以不带）和 `action_token`；处理函数里只在"两边都有 token 且不相等"时才拒绝，所以不带 token 就不校验。真正拦住它的只有全局中间件（需要 owner 凭据或旧的 `X-App-Access-Key`）。结果：持有旧访问密钥的人不带任何参数，就能用 UUID 或短码确认任何人的待确认项，并触发里面冻结的写操作。
2. **同一个确认功能有 4 个路径**（`/agent-chat/inbox/{id}/confirm`、`/agent-chat/routines/{id}/confirm`、`/agent-chat/routines/confirmations/{id}/action`、`/finbot/routines/{id}/confirm`），其中一个来自另一份实现，行为不完全一致（见上）。
3. **旧凭据 `X-App-Access-Key` 是第二扇门。** 全局中间件对所有非 GET 请求接受它；`/knowledge/*` 的写接口、`/v2/*`、`/v3/*`、`/filing-inventories/*`、`/market-data/*`、`/uploaded-evidence/*` 以及全部遗留路由，处理函数自己都不要求 owner 凭据，所以这扇门能直接打开它们。带 `_owner_only` 的接口则仍要求 owner 凭据。
4. **五条遗留写路由还活着**（`/forecasts`、`/forecast-runs`、`/research-runs`、`/forecast-refresh-runs`、`/evidence-revisions/{symbol}`）：处理函数里没有任何身份校验，会调付费模型或往旧表里写假数据（`/forecasts` 写的是 mock 概率）。建议确认是否还有页面在用，没有就下线。
5. **`POST /news-sources/{id}/repair` 传的是 `require_confirm=False`**，绕开了引擎自己为"结构或域名变更"设计的待确认流程；按钮点击被当成同意。新闻源配置是全局的，不分 owner。
6. **`act` 与接口在参数上漂移**，不只是例行任务和 `analyze`：上传材料接口收文件，`save_material_evidence` 只收文字；新闻源、渠道、bot 这类"设置页"能力在 `act` 里整块不存在。给 `act` 加操作时应以接口的参数表为准逐项对照，避免再出现 G1 这种"有操作但缺字段"。
7. **（未核实）`PUT /research-queue` 是整表替换，`act` 是单条增删。** 如果网页端带着旧列表保存，会覆盖掉助手刚加的那一条；我没有去验证前端是否先拉取最新再合并，建议核一下。
8. **（数据旁证）11-24 的新内核 bot 曾回复"暂时不能修改任何数据，包括记交易"**，随后同一天已能出资金卡片；说明 `act` 上线前后有一段"能读不能写"的窗口，对话里的"做不到"回复并不都反映当前能力，所以第二节的证据只采用了仍然成立的三项。
