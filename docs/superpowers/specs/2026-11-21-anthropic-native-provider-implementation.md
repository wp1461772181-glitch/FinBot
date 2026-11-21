# Anthropic 原生通道：实施说明与文档核实结论

- 日期：2026-11-21；对应设计：`2026-11-21-anthropic-native-provider-design.md`
- 代码：`app/anthropic_native.py`（核心）、`app/agent_chat_provider.py`（两个入口分流）、`tests/test_anthropic_native.py`、`scripts/anthropic_native_smoke.py`

## 官方文档核实结论（2026-11-21 读取 platform.claude.com）

| 问题 | 结论 | 出处页面 |
|---|---|---|
| SDK 与 httpx2 | 设计说明写「1.x 基于 httpx2」。实际 1.x 与 2.x 都依赖 `httpx2`，PyPI 最新是 **2.12.0**，本次固定 `anthropic==2.12.0`。纯 Python，加 `jiter`（lock 里已有）、`docstring_parser`（新增）；aarch64 无需编译。 | PyPI 元数据 |
| 鉴权头 | 文档首选 `Authorization: Bearer <key>`，`x-api-key` 是「仍支持的旧写法」。SDK 2.12 默认发 Bearer，本次不改。 | api/overview、manage-claude/authentication |
| 个人密钥要不要 `anthropic-workspace-id` | **看密钥的作用域**：文档写「未绑定到某个工作区的密钥必须带该头；单工作区密钥可省略」。个人密钥创建时可选「单工作区」或「角色允许的所有工作区」，所以 owner 的 `sk-ant-usr-…` 是否需要，取决于当时怎么建的。缺头时 API 返回 400，message 含 `anthropic-workspace-id`。 | authentication#select-a-workspace |
| 档位来源 | Models API `GET /v1/models/{id}` 的 `capabilities.effort` 给出 `supported` 及 `low/medium/high/max/xhigh`（`xhigh` 可为 null）的 `supported`；`capabilities.thinking.types.adaptive.supported` 给出是否支持 adaptive。**可用**，实现按它读取并缓存 6 小时；读失败回退静态表（五档），5 分钟内不重读。 | api/models/retrieve |
| thinking 块回传 | 工具调用未结束时，**整段 `content` 按原样、按顺序**带回，含文本为空的 thinking 块（`signature` 里是加密的推理）。跨轮可以整体不带（可丢最旧的、最新的或全部，不能丢中间一个）。 | build-with-claude/preserved-thinking（+ change-tools-or-instructions） |
| 前缀检查 | 5.5 三个模型都有「preserved thinking」：thinking 块绑定它之前的 `system`、`tools`、所有更早消息。其中任何一处变了，块就失效，请求**可能 400**，也可能不报错而把失效块送给模型（按模型而定）。 | preserved-thinking/prefix-checks |
| 控制项 | beta 头 `thinking-binding-controls-2026-08-01` + `thinking.block_binding.prefix_mismatch_behavior: "drop_block"`：失效块被丢掉、不计费、请求成功；`"error"` 则一律 400。关闭 thinking 时带它会 400。 | prefix-checks#preserved-thinking-controls |
| `refusal` | HTTP 200，`stop_reason: "refusal"`，`stop_details.category`（cyber / bio / frontier_llm / reasoning_extraction / general_harms 或 null）。 | SDK 类型 `RefusalStopDetails` |

## 与设计说明不一致、实施时的取舍

1. **系统消息不全部提到顶层 `system`。** 只有对话开始前的连续 system 消息进 `system`；之后出现的（本轮状态、证据、提示）留在原位置，作为 user 消息里的文本块。理由：(a) 工具循环里这些消息夹在 tool 结果之后，而 `role: "system"` 的消息在 Messages API 里只能放在少数位置；(b) 若把每步都在变的证据和状态提到顶层 `system`，等于每步改写 `system`，前缀检查和缓存都会失效。
2. **每步都变的内容仍在第一条 system 里。** `direct.py` 的 `tool_messages` 在第一条 system 指令末尾写了「已调用工具 N 次，已接受证据 M 条」，每步都变，所以顶层 `system` 每步仍会变：提示词缓存基本只能命中 `tools` 这一段，thinking 块在下一步多半也算失效（交给 `drop_block` 处理）。**要让缓存真正生效，需要把这行状态挪到消息末尾的 system 消息里**——这是对 `direct.py` 提示词结构的改动，没有在这次一并做，见「遗留」。
3. **thinking 回传的保留方式**：选「消息里带内部字段 `_anthropic_content`」，不选「按回合缓存原始块」。理由：`direct.py` 的工具循环（`self.protocol`）本来就按消息保存模型回复，且会按批次裁剪旧批次，字段跟着消息走，裁剪时自然一起丢；按回合缓存要另外维护与 `protocol` 同步的副本。代价：`direct.py` 里复制回复的字段白名单（原 4 个键）必须加上 `_anthropic_content`，否则会被丢掉——已加，并用测试钉住。字段与 `tool_calls` 的 id 对不上时（被裁剪或改过）自动退回「从 content/tool_calls 重建」，不带 thinking，保证不发出残缺块。
4. **未选档位不发 `effort`**（设计说明如此），与其他服务商「没选档位就用环境默认 low」不同。Claude 的模型默认档位 Haiku/Opus 是 medium、Sonnet 是 high，分类类的小调用也会按这个档位思考。想统一成 low，可在 bot 上选档位，或改 `build_request` 一行。
5. **`stream_answer` 没有 effort 参数**（现有签名如此），最终回答不带 `effort`，用模型默认档位。要让最终回答也按 bot 档位，需要给所有调用方加参数，这次没做。
6. **workspace 头**：做成运维开关 `FINBOT_ANTHROPIC_WORKSPACE_ID`（格式 `wrkspc_…`，不合格式则忽略），没有做成每个模型条目上的字段——那要贯穿目录、`AgentRuntimeContext`、`decision_request` 签名，改动面大。缺头时错误码是 `provider_workspace_required`，并有中文提示。需要「不同 key 不同工作区」时再做成条目字段。
7. **`thinking_binding` 的回滚开关**：`FINBOT_ANTHROPIC_THINKING_BINDING=off` 不发 beta 头和 `block_binding`（用 API 默认行为）。默认 `drop_block`，且只在请求里真的带着 thinking 块时才发（每轮第一步和最终回答都不带）。**这是整个方案里唯一没法离线验证的假设**：beta 头与字段在文档里标明 stable，但没有真实调用验证，冒烟脚本第 4、5 步专门测它。

## 回滚

- `FINBOT_ANTHROPIC_NATIVE=off`：`anthropic` 条目回到兼容接口（`https://api.anthropic.com/v1/chat/completions`，没填地址时用这个默认值），行为同上一分支；目录里的档位随之显示为不支持。
- 其他服务商的路径没有改动一个字节：测试对 openrouter、deepseek 在开关开/关两种状态下的请求体和请求头做了钉死对照。

## 错误码

沿用现有命名；新增两个：`provider_refusal`（附 `category`，界面提示「模型拒绝回答」）、`provider_workspace_required`。SDK 重试设为 0，超时与看门狗仍由 FinBot 现有逻辑负责。

## 遗留

- `ANTHROPIC_CUSTOM_HEADERS` 环境变量会被 SDK 读入默认请求头（`ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、profile 文件已被显式参数屏蔽，有测试）。盒上不设这个变量即可；如要彻底屏蔽，需包一层清环境变量。
- 每步变化的状态行（上文第 2 点）阻碍缓存命中，是缓存收益的最大单项，建议单独做。
- `tools` 为空但历史里有 `tool_use` 的请求在 Messages API 上是否被接受未核实；FinBot 的收尾回答不带 protocol，目前不会出现。
