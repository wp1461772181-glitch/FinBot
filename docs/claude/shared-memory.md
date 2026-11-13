# FinBot 共享记忆（两台机器的 Claude 共用）

> 用途：owner 的两台机器（Mac 本地、Muse 的 VM）上的 Claude Code 记忆默认不互通。本文件是**仓库内的共享 canonical**——只装稳定事实，经仓库根 `CLAUDE.md` 的 @ 引用在开工时自动加载。易变的状态（包进度、派工、待拍板项）不在这里，由操作员（Daniel）的工作区维护；本文件由操作员在事实变化时更新，任何一边的 Claude 发现与现实不符，先报 owner，不要自行改写本文件。
> 最近更新：2026-11-13（操作员建立）。

## 产品定位

- FinBot 是**个人金融助手**。单公司证据链（先找证据、再形成判断）是它的深研能力之一，不是产品边界；组合级问题走 `query_portfolio`。
- 可以给买入/卖出**意见供参考**，决定权在用户；**永不执行交易**。
- 预测修订的材料必须由用户在卡片上勾选，agent 不得代选来源；没有候选就直说。

## 设计准则

- 三条核心准则在仓库根 `CLAUDE.md`（owner 2026-11-04 定），是全系统设计的最高依据，先于任何具体方案。
- 「AI 回答 + 新闻」设计规则全文：`docs/finbot-design-rules.md`（含每条规则的出处与事故背景；基线为 2026-11-12 的 main 与 D-F 裁定，引用前注意基线日期）。

## 生产拓扑（2026-11-13 时点）

- 后端跑在**黑豹 X2 盒**（RK3566 小盒）：API + Telegram bridge + sentinel + 本地 PostgreSQL（权威数据源）；前端在 GitHub Pages。
- 盒上源码不是 git 检出，发布走 **archive-swap**（整树替换 + 搬运 .env 与 data/ 运行时文件）。
- RAG 已迁回盒上：pgvector 存 6,026 条向量，瘦后端 `finbot-rag-slim` 在盒 127.0.0.1:8766；embedding（BAAI/bge-m3）与 rerank（BAAI/bge-reranker-v2-m3）走 SiliconFlow API。瘦后端**没有增量索引**，新入库文档不会自动进向量库。
- Supabase 只剩 2026-11-03 迁移时的冻结回滚副本，生产不依赖它。

## 模型与核查（盒上 catalog，2026-11-13 时点）

- 默认对话模型 `haiku-5.5`（OpenRouter，owner 自选）；另有 `muse-ember`、`gpt-6.1-terra`（OpenRouter）、`deepseek-flash`/`background`（SiliconFlow DeepSeek-V4-Flash）、`glm5.3-flash`（智谱）。
- 后台角色：earnings=muse-ember、forecast=gpt-6.1-terra；声明法官影子通道 = glm-5.3-flash。
- 旧数字核查线已停标：`CLAIM_NUMBER_REVIEW=off`（FP0，2026-11-11 上线）——它不再改答案状态、不加脚注、不删句；对外可见的核查标注只走法官的统一公门。

## 协作分工（owner 2026-11-06 定，2026-11-13 更新额度口径）

- 设计默认 Sonnet（high）；实施默认 Haiku（--effort xhigh 显式带）；Opus/Fable 只在 owner 点名时用；贵价席位派工死亡先报 owner、不自动接力。
- 测试类跑（回放、冒烟、对比）默认用便宜的 Muse Ember + Haiku 5.5；生产通道不因此变。
- owner 已开 Claude Max 5x（2026-11-11），不再有「省额度」的旧规则——Mac 本地记忆里 10 月写的额度紧、Opus 只读、Sol 审计、DeepSeek 执行等分工文件均已被本节取代。
- 与 owner 交流：简体中文，结论先行；写代码/跑命令不算完成，可核验的结果才算。

## 活文档在哪

- Fable 5.2 实施方案（FP0–FP13）、D-F0–F7 裁定、验收报告与实时进度：不在仓库，在操作员（Daniel）的工作区，需要时问 Daniel，不要凭本文件猜进度。
- 本仓库 `docs/` 其余文件多为各阶段施工图与验收报告，是历史技术文档，不是路线图。
