# Claude 直连改走 Anthropic 原生接口（Messages API）

- 日期：2026-11-21
- 提出：owner；设计：Opus。owner 在三个方案里选了「A 接原生接口」。
- 风险等级：**高**（涉及密钥与鉴权、所有模型调用的公共通道）。按协作分工，验收由 Fable 负责。
- 依赖：分支 `claude/model-provider-ux`（新增 `anthropic` 等服务商）合入 main 后再开工，本分支以合入后的 main 为基线。

## 为什么改

owner 在 Claude Console 有额度，目前通过 Anthropic 的 **OpenAI 兼容接口**（`https://api.anthropic.com/v1` 的 chat/completions）直连 Claude Haiku / Sonnet / Opus 5.5。官方文档（OpenAI SDK compatibility 页，2026-11 读取）写明：

- `reasoning_effort` 被**忽略**。Claude 5 系列只能用默认强度（Haiku、Opus 默认 medium，Sonnet 默认 high）。
- 兼容层「主要用于测试和对比，不建议用于正式生产」，而且**不支持提示词缓存**。
- 回答里拿不到思考内容。

所以，要让思考强度真正生效，只能走原生的 Messages API（`POST /v1/messages`）。同时还能用上提示词缓存（缓存命中部分按约 1/10 计价），让 owner 的额度更耐用。

## 目标

1. provider 为 `anthropic` 的模型条目改走原生 Messages API；FinBot 其他代码不需要知道这一变化。
2. 思考强度真正生效：`output_config.effort` 按模型可选的档位发送；目录里 `supported_efforts` 显示每个模型真实支持的档位。
3. 开启提示词缓存。
4. 工具调用、流式输出、超时与进度看门狗、错误分类、输出上限等现有保护，行为与现在一致。

## 不做（非目标）

- 不改 FinBot 内部的消息格式。内部仍使用 OpenAI 形状（`role`/`content`/`tool_calls`/`tool`），只在出入口这一层做转换。
- 不改其他服务商的通道。
- 这次不在界面上展示 Claude 的思考摘要（可作为后续项；这次只把它收进现有的 `reasoning_collector`，不新增界面）。
- 不做 Bedrock / Vertex 等第三方平台。

## 反目标（出现即算失败）

- 完整密钥出现在日志、审计、异常信息里。
- 工具调用循环里丢失或改写了 Claude 的 thinking 块，导致 400 或思考失效（见下文「思考块回传」）。
- 其他服务商的请求体、请求头因这次改动发生任何变化。
- 因为切到原生通道，owner 现有的三个 Claude 条目（provider 为 `custom`、地址指向 Anthropic）失效。

## 方案（已定部分）

### 1. 接入位置：在现有两个入口里分流

`app/agent_chat_provider.py` 只有两个对外入口：`decision_request`（工具决策，返回 OpenAI 形状的 `(data, message)`）和 `stream_answer`（最终回答，逐段 yield 文本）。所有调用方——主流程 `direct.py`、摘要、画像提取、法官、财报、预测——都只经过这两个函数。

- 在这两个函数开头按 `provider == "anthropic"` 分流到新模块（建议 `app/anthropic_native.py`），返回值形状保持不变。
- 新模块负责三件事：OpenAI 形状 → Anthropic 请求的转换、发送请求、Anthropic 流式事件 → OpenAI 形状的回转。

### 2. 用官方 Python SDK

按 Anthropic 的要求，新代码用官方 `anthropic` SDK，不手写 HTTP。注意事项：

- `anthropic` 1.x 基于 `httpx2`，不能传入现有的 `httpx` 客户端和传输层。地址固定为 `https://api.anthropic.com`，不接受用户自填的 Base URL，因此不需要现有的 IP 钉扎传输（那是为用户自填地址防 SSRF 准备的）。
- 运维通过 `MODEL_EGRESS_PROXY` 设置的出口代理照样要生效：用 SDK 的 `DefaultHttpxClient(proxy=...)` 接入。
- SDK 自带的重试（默认 2 次）要与 FinBot 现有的超时和看门狗协调。建议把 SDK 重试设为 0，交给现有逻辑处理，避免超时被成倍放大。
- 每收到一个流式事件就调用 `mark_progress()`，继续让现有的 `progress_watchdog` 生效。
- 在 `requirements` 里固定 `anthropic` 的版本；还要确认盒子（RK3566 / aarch64）上能装。

### 3. 请求转换（OpenAI 形状 → Messages API）

- `system` 消息：合并后放进顶层 `system`。
- `assistant` 消息里的 `tool_calls` → `tool_use` 块；参数 JSON 字符串解析成对象。
- `role: "tool"` 消息 → 下一条 `user` 消息里的 `tool_result` 块。同一批工具调用的结果必须放在**同一条** user 消息里。
- 工具定义 `tools[].function` → `{name, description, input_schema}`；`tool_choice` 用 `auto`（Claude 5.5 不支持强制调用）。
- 不发送 `temperature` / `top_p`（Claude 5 系列只接受默认值）。
- `max_tokens` 沿用 `MAX_OUTPUT_TOKENS`（32768），走流式。
- 思考：`thinking: {type: "adaptive", display: "summarized"}`；强度：`output_config: {effort: <档位>}`。bot 没选档位时不发 `effort`，使用模型默认值。
- 缓存：顶层 `cache_control: {type: "ephemeral"}`（自动缓存）。

### 4. 思考块回传（关键）

Claude 5.5 的 thinking 块与模型和对话绑定。在一次回合的工具循环里，下一次请求必须原样带回上一轮 assistant 的全部内容块，包括 thinking 块，否则可能 400 或思考失效。

- 新模块返回的 `message` 里，额外保存这条 assistant 消息的**原始内容块**，用一个内部字段，例如 `_anthropic_content`。下一次转换时，凡是带着这个字段的 assistant 消息，就直接用原始块，不再从 `content`/`tool_calls` 重建。
- 实施方必须核实：FinBot 在工具循环里把模型回复放回 messages 的路径，会不会保留这个字段。如果中途有复制、序列化或裁剪，要么在那里放行这个字段，要么改用按回合缓存原始块的办法，二者选一并说明理由。
- 跨回合的历史（存库、只留最终文本）可以不带 thinking 块，这是允许的；实施方要以官方文档为准核实。
- 测试要钉住：工具循环第二步的请求里，原样带有第一步的 thinking 块。

### 5. 响应回转（Messages 流式事件 → OpenAI 形状）

- `text` 增量 → `content`；`tool_use` 块和 `input_json_delta` → `tool_calls`，`index` 从 0 连续编号，`id` 用 Anthropic 的 `tool_use.id`。
- 思考摘要 → `reasoning_content`，送进 `reasoning_collector`。
- `stop_reason` 对应关系：`end_turn` → `stop`；`tool_use` → `tool_calls`；`max_tokens` → `length`（沿用现有规则：截断的工具调用算失败）；`refusal` → 返回明确的错误码（例如 `provider_refusal`），附上 `stop_details.category`；`pause_turn` 不应出现（不用服务端工具），一旦出现按不完整处理。
- `usage` 原样转为现有字段（`prompt_tokens` / `completion_tokens`），缓存读写的 token 数也一并记入。
- 现有的各项检查（流不完整、超出大小、工具调用数量上限等）在原生通道上都要有对应实现，错误码沿用现有命名。

### 6. 鉴权

- 原生接口用 `x-api-key` 头，由 SDK 处理。
- owner 的密钥是个人类型（`sk-ant-usr-…`）。官方文档说明：不属于某个工作区的个人或服务账户密钥，要带 `anthropic-workspace-id` 头。现在兼容接口没带这个头也能调通，实施时要核实原生接口是否同样不需要；如果需要，在模型条目上加一个可选的「工作区 ID」字段，并在弹窗里提示。
- 拉模型列表：原生 `GET /v1/models`（带 `x-api-key` 和 `anthropic-version`），如果 `claude/model-provider-ux` 分支已经实现，直接复用。

### 7. 档位从哪来

- 首选 Models API 返回的 `capabilities` 字段（实时、按模型）。实施方先核实它是否给出可用的 effort 档位；如果给出，`_reasoning_fields` 对 `anthropic` 条目从这里读取（带缓存，失败时回退到下面的静态表）。
- 静态表（2026-11 官方文档）：Haiku 5.5、Sonnet 5.5、Opus 5.5 都支持 `low / medium / high / xhigh / max`；默认值 Haiku 和 Opus 是 `medium`，Sonnet 是 `high`。FinBot 档位到 Anthropic 的映射：`low/medium/high/xhigh/max` 一一对应；`none`、`minimal` 不在这三个模型的档位里，不显示。
- `NATIVE_EFFORTS` 里 `anthropic` 的登记（上一分支登记为 `()`）改为上述档位，保持「界面显示的档位 = 真正会发送的档位」。

### 8. 迁移 owner 现有的三个条目

- owner 现有三个条目的 provider 是 `custom`，地址是 `https://api.anthropic.com/v1`。**不自动改写。**
- 可以在模型卡片上提示：「这是 Anthropic 的兼容接口，改用 Anthropic 服务商可以使用思考强度和缓存」，由 owner 自己编辑切换。编辑时需要重新填 key（现有规则：换了服务会清空 key）。

## 拒答与回退

- Claude 5.5 的安全分类器可能拒答（`stop_reason: refusal`）。官方建议为 Opus / Sonnet 5.5 默认开启服务端回退（`fallbacks: "default"` 加 beta 头 `server-side-fallback-2026-07-01`）。Haiku 5.5 没有服务端回退。
- Opus 的判断：金融研究问答被拒的概率不高，这次先**不开**回退，只把拒答以明确的错误码报出，并在界面上显示「模型拒绝回答」。开回退会让请求悄悄换成另一个模型，与「用户选什么模型就用什么模型」的原则冲突。如果 owner 想开，可以作为后续开关。

## 约束

- 测试：转换和回转逻辑必须是纯函数，单元测试覆盖：多轮工具调用、并行工具调用、思考块回传、拒答、`max_tokens` 截断、usage 与缓存字段。SDK 调用用 mock，测试里不发真实请求。
- 全量后端测试不能新增失败（用 `.venv-rag`；基线有 2 条因测试顺序导致的失败，单独跑能过）。
- 真实调用只允许 owner 本人在盒上或本地用自己的 key 做冒烟测试，实施方不使用 owner 的 key。可以提供一个冒烟脚本，由 owner 运行。
- 开关：`FINBOT_ANTHROPIC_NATIVE`，默认 on。off 时 `anthropic` 退回兼容接口（即上一分支的行为），作为线上回滚手段。

## 留给实施方决定的

- 新模块的具体结构、函数命名。
- SDK 版本号（在 requirements 里固定）。
- `_anthropic_content` 的具体名字，以及它在工具循环里的保留方式（见第 4 节，必须说明理由）。
- 拒答在界面上的具体措辞。
