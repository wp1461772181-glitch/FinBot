# 后台「添加模型」改进：服务商补全、模型列表、密钥核对

- 日期：2026-11-21
- 提出：owner；设计：Opus（与 owner 对话定稿，owner 已同意方案）
- 范围：设置 → 模型 的添加/编辑弹窗（`frontend/src/app/settings/models/ModelDialog.tsx`）及其后端（`app/agent_chat_api.py`、`app/agent_model_catalog.py`、`app/agent_chat_provider.py`）

## 为什么改

owner 加 Claude（Haiku / Sonnet / Opus 5.5）时遇到三个问题：

1. **常见服务商没有**：Anthropic 这类常用服务商不在列表里，只能选「自定义」并自己查、自己填 Base URL。
2. **模型列表太短**：「服务商可用模型」最多显示 5 个，OpenRouter 这种有几百个模型的服务商根本看不全。前端 `result.models.slice(0, 5)` 和后端 `items[:5]` 两处都截断了。
3. **密钥填完看不到**：输入框是密码框，保存后也没有任何能认出是哪一把密钥的显示，没法确认填对没有。

## 目标

- 选中服务商后，Base URL 自动带出，并能拉到该服务商的模型列表。
- 模型列表完整、可搜索，输入「claude」就能筛出来。
- 填写时能看到密钥明文；保存后能看到密钥的头尾特征（例如 `sk-ant-usr-1js…xgAA`），足以认出是哪一把。

## 不做（非目标）

- 不做一次添加多个模型（owner 没提，可以以后再说）。
- 不为新服务商写原生（非 OpenAI 兼容）的请求方式。
- 不给新服务商加思考深度参数：新服务商一律不发 reasoning 参数，与现在的「自定义」一致；以后按需单独加。
- 不改浏览器本地的「个人模型配置」（`model-profiles.mjs` 的本地存储与校验逻辑），只补它共用的服务商列表。

## 反目标（这样就算失败）

- 服务器把**完整**的已存密钥发回网页。现有设计是加密存储、从不外发，这一点不能破。
- 密钥（包括头尾特征以外的部分）出现在日志、审计记录或报错信息里。
- 已有的模型条目、bot、后台角色因为这次改动而失效。

## 方案

### 1. 服务商补全

前后端各补 6 家，都走它们的 OpenAI 兼容接口：

| provider | 显示名 | Base URL |
|---|---|---|
| `anthropic` | Anthropic（Claude） | `https://api.anthropic.com/v1`（owner 已实测可用） |
| `openai` | OpenAI | `https://api.openai.com/v1` |
| `gemini` | Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `xai` | xAI（Grok） | `https://api.x.ai/v1` |
| `mistral` | Mistral | `https://api.mistral.ai/v1` |
| `groq` | Groq | `https://api.groq.com/openai/v1` |

- 要改的地方：后端 `PROVIDER_NAMES`、`BASE_URLS`、`PROVIDERS`（chat/completions 地址），前端 `model-profiles.mjs` 的 `CATALOG`（含建议的 Model ID 占位）。
- 前后端两份列表保留各自原有的形态，改动最小。另加一条测试，钉住前后端的服务商集合与地址完全一致，以后漏改一边就会报错。（Opus 的取舍：前端列表还被本地个人配置的校验使用，改成由后端下发的牵连面太大。）
- 已存的条目（含 provider 为 `custom`、地址指向 Anthropic 的那三条）不迁移、照常可用。

### 2. 模型列表

- 后端去掉 `items[:5]`，返回完整列表。如果担心体积，可以设一个宽松上限（例如 1000 条），并告诉前端结果被截断了。
- 前端把「服务商可用模型」下拉换成**可搜索的选择框**：输入关键字按 id 和名称过滤，不限条数，长列表可滚动。仓库里已有的 UI 组件优先，没有合适的就用最少的新代码实现，不引入大依赖。
- **Anthropic 拉模型列表**：`GET https://api.anthropic.com/v1/models` 要求带 `x-api-key` 和 `anthropic-version` 请求头，只带 Bearer 可能会被拒。实施时先核实；如果确实需要这两个头，就为 `anthropic` 单独处理。其他新服务商按现有 Bearer 方式拉 `/models`，遇到不支持的，沿用现有的 `unsupported` 提示（「可手动填写 Model ID」）。

### 3. 密钥核对（owner 选了方案 B）

- **填写时**：API key 输入框加一个显示/隐藏（眼睛）按钮，默认隐藏，点开显示明文。
- **保存后**：服务器给每个由弹窗填写、加密保存（vault）的条目返回 `key_hint`，规则如下：
  - 密钥长度 ≥ 20：取前 12 个字符 + `…` + 后 4 个字符。
  - 更短的密钥：只显示 `…` + 后 4 个字符。
  - `key_hint` 由服务器在保存时根据明文算好并存起来，或者读取时解密后现算；无论哪种方式，**完整密钥都不出服务器**，`key_hint` 也不写进日志。
- 编辑弹窗里，密钥框的占位文字从「不改就留空」改为显示 `key_hint`，例如「当前：sk-ant-usr-1js…xgAA，不改就留空」。模型卡片（`ModelCard.tsx`）上也显示 `key_hint`。
- 读环境变量的条目（env 模式）不显示 `key_hint`，保持现状：只显示变量名和是否已配置。
- 「测试并保存」本身就会用密钥真实调用一次，密钥填错会直接报错，不会被保存。

## 约束

- 前后端改动都要有测试：后端用 `.venv-rag` 跑 pytest，前端跑相关的 `node --test frontend/scripts/*.test.mjs`。前端构建要能通过，首屏体积不能明显变大（仓库有首屏体积的记录，参考最近的 P8 提交）。
- 中英文案按仓库的 i18n 约定补齐，不留孤儿 locale 词条。
- 不改动与本需求无关的代码。

## 留给实施方决定的

- 可搜索选择框的具体实现（用现有组件组合，还是很小的新组件）。
- `key_hint` 是保存时存一份，还是读取时现算。
- 模型列表上限设多少，以及截断后怎么提示。
- 6 家新服务商的建议 Model ID 占位文字。
