# 输入框的模型与思考强度选择器：AI Elements Model Selector + A2 质感

- 日期：2026-11-21
- 提出：owner；设计：Opus。owner 看过三版效果图和实机试跑后拍板：用 AI Elements 的现成 Model Selector，再叠加「A2 更有表现力」的质感。
- 范围：聊天输入框左下角的模型/强度入口（`frontend/src/app/chat/ModelEffortPicker.tsx`，逻辑在 `frontend/src/model-effort.mjs`）

## 为什么改

现在的入口是一行灰字「模型 · 强度 ▾」，点开后是一列带勾的纯文字模型，下面再一列 7 档强度。几个问题：没有搜索；看不出模型属于哪家服务商；强度只能一行一行选；整体太平，不够美观。owner 的要求是「合理、不突兀，但又美观」。

## 已定的做法（owner 已确认）

1. **面板用 AI Elements 的 Model Selector**，即居中弹出、可搜索的命令面板（来源：`https://registry.ai-sdk.dev/model-selector.json`）。
   - 它本质上只是对项目已有的 `Command` 和 `Dialog` 包了一层：一个面板、一个搜索框、按服务商分组的列表、服务商 logo。
   - 用 shadcn CLI 拿到的文件是 `src/components/ai-elements/model-selector.tsx`。
   - **不要**带上 CLI 顺手加的 `cn` 依赖。安装时会问是否覆盖已有的 `dialog.tsx`、`command.tsx`，一律选不覆盖。
2. **思考强度放在面板底部，做成分段按钮**（这几个库都没有现成的强度控件，由我们自己做）：
   - 滑块切换时带回弹动画。
   - 每档前面有表示高低的小竖条；右上角一句话说明当前档位，例如「均衡，多数问题够用」。
   - 只显示这个模型实际支持的档位，加上「默认」。
3. **A2 质感**：
   - 面板用毛玻璃效果（半透明表面加背景模糊），阴影更柔和、有层次。
   - 选中的模型行用渐隐的蓝色底，左侧加一条蓝色细线。
   - 强度越高，滑块光晕越亮，颜色从蓝过渡到紫；最高一档的文字用蓝紫渐变。
   - 输入框入口：服务商 logo + 模型简称 + 档位竖条 + 档位字。档位处于高位时，档位字也用同样的渐变。
   - 渐变**只出现在强度这一处**，界面其他地方不加渐变。
4. **服务商 logo 放进项目本地**：models.dev 的 logo 下载到前端静态资源目录，不从外网加载（离线和国内网络下都稳定，也不会向第三方泄露访问）。
   - 用到的服务商：anthropic、openai、google、xai、mistral、groq、deepseek、openrouter、moonshotai（Kimi）、alibaba（通义）、zhipuai、siliconflow；models.dev 有的就拿，没有的用通用图标兜底。
   - OpenRouter 的条目按模型 ID 的厂商前缀显示 logo，例如 `anthropic/claude-…` 显示 Anthropic 的 logo。
   - 在 `THIRD_PARTY_NOTICES.md` 里注明 logo 来源。
5. **深色模式**：logo 自动反色（组件自带 `dark:invert`，按 FinBot 的 `data-theme="dark"` 生效）；毛玻璃和光晕在深色下也要协调。

## 必须保持不变的行为

- 选择后立即保存（`updateBot`）。选模型后面板保持打开，方便接着选强度；选强度后面板关闭。保存失败时面板保持打开，显示原因，入口上的显示不变。
- 保留「服务器默认模型」这一项；「缺 key」照常标出；模型不支持强度时显示「该模型不支持思考强度」；当前值不在模型档位内时，照现有的 `effortChoices` 逻辑提示「不在该模型的档位内」。
- 底部保留那句「模型和 key 只在服务器上，浏览器不保存 key。」。
- 不禁用任何选项、不替用户自动切换（model-effort.mjs 头部注释写明的原则）。
- `model-effort.mjs` 的纯逻辑和它的测试保持；可以新增函数（例如分组、选 logo），但已有函数的行为不变。
- 无障碍：搜索框加上下键选模型、回车确认（cmdk 自带）；强度是一个可以用 Tab 进入的单选组（radiogroup），有 `aria-checked`；面板有标题，供屏幕阅读器读出。
- 手机上：沿用项目现有的「宽屏用弹窗、窄屏用底部抽屉」惯例（参考 `ModelDialog.tsx` 和 `PopPanel`），内容一致。

## 约束

- **首屏体积**：输入框属于首屏。面板内容（Command 列表、logo）尽量按需加载，打开面板时再加载，首屏只多入口按钮那一点。要报告首屏去哈希字节数的变化，参考 P8 系列提交里的测法。
- 用项目现有的设计变量（颜色、圆角、字号、阴影），不硬编码与主题冲突的颜色；渐变色值集中定义一处。
- 动画要尊重系统的「减少动态效果」设置（`prefers-reduced-motion` 时去掉回弹和光晕动画）。
- 测试：前端跑相关的 `node --test`（`model-effort.test.mjs` 等），构建必须通过；仓库里的冒烟测试如果覆盖了入口按钮（`data-testid="model-badge"` 等），保持这些选择器可用，或同步更新。
- 中英文案按 i18n 约定补齐，不能留下孤儿词条。

## 不做

- 不改后端，不改模型目录接口。
- 这次不碰对话里的其他组件（Reasoning 折叠、行内引用、上下文用量），那些另外再评估。
- 不改「设置 → 模型」的添加/编辑弹窗。那是另一个分支 `claude/model-provider-ux` 的工作，两边不要碰同一批文件。

## 留给实施方决定的

- 毛玻璃、阴影、光晕的具体数值（参考效果图 `.superpowers/brainstorm/*/content/model-picker-a-v2.html` 里 A2 的写法）。
- 档位说明的具体措辞。
- 模型行是否显示能力小图标（思考、工具、看图）：目录数据里有就显示，没有就不显示，不为它新增接口。
