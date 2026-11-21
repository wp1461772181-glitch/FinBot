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

## 实施取舍（含 2026-11-21 验收返工后的最终口径）

1. **缓存：只在最后一个工具定义上放一个显式断点，不用顶层自动缓存。** FinBot 每一步都改写第一条 system（「已调用工具 N 次」）和尾部消息，自动缓存把断点放在最后一个块上，每次都按 1.25 倍价格写入、几乎读不到，比不缓存还贵。工具列表是唯一稳定的前缀，所以断点放在它上面。**system 段目前仍不缓存**：要让它也命中，需要把 `direct.py` 里的状态行挪到消息末尾，这会影响所有服务商，是另一项工作，这次不做。
2. **thinking：默认 `strip`。** `FINBOT_ANTHROPIC_THINKING_BINDING` 取值 `strip`（默认）、`drop_block`、`off`。主循环每一步都会改写前缀（状态行、证据、裁剪旧批次），上一步的 thinking 块在下一步都过不了前缀检查，所以带回去也换不来推理延续，只多了体积；而 5.5 模型在没设 `prefix_mismatch_behavior` 时「可能 400」，所以不能用「不发控制项但仍带块」当回滚。`strip` 在 `convert_messages` 里去掉历史里所有 thinking / redacted_thinking 块，且默认不再把原始块存进 `_anthropic_content`，不依赖任何 beta，官方明确允许整体不带。`drop_block` 带块并附 beta 头 `thinking-binding-controls-2026-08-01`，失效块被服务端丢掉；`off` 带块但不附控制项（只用于冒烟里观察 API 的反应）。写错取值按 `strip` 处理并告警一次。响应里的 `input_transformations` 随 `data` 返回，`direct.py` 按类型计数记入 audit（`audit.input_transformations`）。
3. **中途出现的 system 消息：白名单，不是排除法。** 开头的 system 消息进顶层 `system`。之后出现的消息，只有 FinBot 的**完整固定指令串**（`CITATION_V2_NOTE`、`CLOSING_RETRY_NOTE`、`Turn.model` 重试时那句 `Use native structured function calls…`，整串精确比较，不做前缀匹配）才在合法位置（跟在 user 或 tool_result 之后，并且是最后一条或后面跟着 assistant）合并成一条 `role: "system"` 发出。**其余一律作为 user 文本**：理解提示（带用户原话）、状态和目录（带工具报错、抓取文档的标题与预览）、证据、被省略数字的摘要、历史对话召回、引用了模型草稿的 nudge——这些都可能含别人写的文字，不该获得 system 权限。它们放进前面那条 user 消息里，保证 system 后面永远不是 user。只有 5.5 三个模型发 `role: "system"`，其他模型一律 user 文本。白名单里的字符串来自 `direct.py` 的常量，有测试核对它们仍是 `direct.py` 真实发送的串、且各种带载荷的消息不在白名单里。代价：理解提示等带载荷的指令在 Claude 这条通道上不再有 system 权限（兼容接口时代它们被提到开头，是 system）；要恢复需要 `direct.py` 把静态指令和动态载荷拆成两条消息，另议。
4. **空 key 在入口拒绝。** `api_key` 为 None、空或只有空白时直接抛 `provider_invalid_key`，不构造客户端：SDK 对 None 会去读 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、profile 文件。
5. **SDK 延迟 import。** `anthropic_native` 顶层不 import SDK；开关 off 时完全不碰它，目录展示也不需要它。没装 SDK 而开关 on 时，请求失败码是 `provider_sdk_missing`（带中文提示）。测试用子进程在 SDK 不可 import 的环境里验证三个模块都能导入。
6. **档位口径。** 和其他服务商一致：bot 选了档位就发；没选则取 `AGENT_REASONING_EFFORT`（默认 low，写 `default` 则不发）；`none` / `minimal` 映射成 `low`。最终回答（`stream_answer`）同样按环境默认发。只发模型支持的档位（以 Models API 为准）。
7. **静态回退表只属于 5.5 三个模型。** Models API 读不到时，`claude-haiku-5-5`、`claude-sonnet-5-5`、`claude-opus-5-5`（及无型号时的目录默认视图）按五档 + adaptive；其他 claude 模型不发 adaptive 也不发 effort。
8. **SDK 会自己读的环境变量。** 构造客户端和首次 import 期间屏蔽 `ANTHROPIC_CUSTOM_HEADERS`、`ANTHROPIC_LOG`（之后恢复）；`open_telemetry={"traces": False}` 让 SDK 不再读 `ANTHROPIC_OPEN_TELEMETRY*`。设了这些变量会告警一次（只写变量名）。若 SDK 已被别处先 import，`ANTHROPIC_LOG` 在那次 import 时已生效，盒上不要设。
9. **错误翻译只包住发送和读流。** `translate()` 只用于流迭代和 `get_final_message()`；`build_request` / `convert_messages` 里 FinBot 自己的 bug 原样抛出，不会被当成服务商错误重试。
10. **`refusal`**：错误码 `provider_refusal`，不重试；`category` 记入 audit（`audit.refusal.category`）；界面文案「模型拒绝回答」。
11. **workspace 头**：运维开关 `FINBOT_ANTHROPIC_WORKSPACE_ID`（`wrkspc_…`，格式不对告警一次并忽略），不做成条目字段（要改目录、运行上下文和函数签名）。缺头的错误码 `provider_workspace_required`。

## 盒上部署步骤（archive-swap 不装依赖，必须先装包）

换包**之前**，在盒子的 venv 里：

```bash
pip install anthropic==2.12.0 docstring_parser==0.18.0
python -c "import anthropic; print(anthropic.__version__)"   # 必须成功，输出 2.12.0
```

之后再换整树。顺序反了的后果：没装 SDK 时 anthropic 条目的请求会失败（`provider_sdk_missing`）；这时把 `FINBOT_ANTHROPIC_NATIVE=off` 写进 `.env` 并重启，就回到兼容接口，目录和其他服务商不受影响。三个新环境变量已写进 `.env.example`。

## 冒烟

owner 用自己的 key，对三个模型各跑一遍：`scripts/anthropic_native_smoke.py --model claude-haiku-5-5`（再换 `claude-sonnet-5-5`、`claude-opus-5-5`）。需要关注的输出：第 3 步第二次调用的 `cache_read_input_tokens`（system 相同、问题不同）；第 4、5a 步的 `input_transformations`（失效块是否被丢）；5b 的结果（`off` 下 API 是 400 还是放行，决定「带块但不设控制项」是否安全，默认已不用它）；5c 必须成功；第 6 步 low 与 max 的输出量和耗时是否有差别。

## 回滚

- `FINBOT_ANTHROPIC_NATIVE=off`：`anthropic` 条目回到兼容接口（地址取 main 里 `PROVIDERS["anthropic"]`，即 `https://api.anthropic.com/v1/chat/completions`），行为同上一分支；目录显示「不支持思考强度」。
- 其他服务商的路径没有改动一个字节：测试对 openrouter、deepseek 在开关开/关两种状态下的请求体和请求头做了钉死对照。

## 遗留与后续（只记录，未改）

- **system 段缓存**：要命中需把 `direct.py` 里的状态行挪到消息末尾（影响所有服务商）。做完后可在最后一条 leading system 上加第二个显式断点。
- **direct.py 改为只追加**（状态写在末尾的 `role: "system"` 消息、不移动旧文本、不裁剪旧批次）之后，`drop_block` 才有意义，thinking 才能真正跨步延续；此前 `strip` 与 `drop_block` 对模型效果相同。
- **材料分析通道**（`app/model_providers.py`）是独立的 OpenAI SDK 通道，anthropic 在那里仍走兼容接口并带 `temperature: 0`；设计说明里「所有调用方都只经过这两个函数」不含它。不在本次范围。
- **`stream_answer`** 目前 app 里没有调用方使用，它的档位口径只有测试覆盖。
- **`MODEL_EGRESS_PROXY`** 在原生通道上对所有请求生效；现有通道只对填了地址的条目生效。对 owner 现有的 custom 条目口径一致。
- 环境变量格式告警在首次使用时发出一次，不是进程启动时。
