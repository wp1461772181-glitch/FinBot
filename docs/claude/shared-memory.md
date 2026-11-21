# FinBot 共享记忆（两台机器的 Claude 共用）

> 用途：owner 的两台机器（Mac 本地、Muse 的 VM）上的 Claude Code 记忆默认不互通。本文件是**仓库内的共享 canonical**——只装稳定事实，经仓库根 `CLAUDE.md` 的 @ 引用在开工时自动加载。易变的状态（包进度、派工、待拍板项）不在这里，由操作员（Daniel）的工作区维护；本文件由操作员在事实变化时更新，任何一边的 Claude 发现与现实不符，先报 owner，不要自行改写本文件。
> 最近更新：2026-11-21（新增前置硬编码审计一节；顺带修正 embedding 通道）。

## 产品定位

- FinBot 是**个人金融助手**。单公司证据链（先找证据、再形成判断）是它的深研能力之一，不是产品边界；组合级问题走 `query_portfolio`。
- 可以给买入/卖出**意见供参考**，决定权在用户；**永不执行交易**。
- 预测修订的材料必须由用户在卡片上勾选，agent 不得代选来源；没有候选就直说。

## 设计准则

- 三条核心准则在仓库根 `CLAUDE.md`（owner 2026-11-04 定），是全系统设计的最高依据，先于任何具体方案。
- 「AI 回答 + 新闻」设计规则全文：`docs/finbot-design-rules.md`（含每条规则的出处与事故背景；基线为 2026-11-12 的 main 与 D-F 裁定，引用前注意基线日期）。

## 前置硬编码审计（2026-11-21，owner 要求排查）

- 背景事故：长期记忆曾误存一条普通提问（2026-11-16），根因是记忆兜底路径凭关键词表在提取模型无产出时逐字落库、无模型复核——`authorization.py` 的 `_STANDING_INSTRUCTION` 是子串匹配，「分别用」误中「别用」。该条已删，全库同类仅此一条。
- 审计口径：内容在交给模型之前先被写死规则（正则、关键词表、阈值、子串校验）筛查，筛不过就丢弃、截断、改写或不调模型。Sonnet 只读审计结论：主清单语义判断类 17 条、授权安全类 7 条、纯技术类 26 条，另有边界情况 8 条。完整报告与大白话版在私有仓库 claude-sync 的 `progress/finbot-prehardcode-audit-2026-11-21.md` 与 `progress/finbot-prehardcode-audit-plain-2026-11-21.md`。
- 共同模式：做得对的位置都留痕并告知模型（如 `truncation_events`）；问题集中在「被筛内容模型完全看不到、也不被告知」：首轮序数词整轮打回（M-1）、证据实体字面闸（M-3）、模型读调用的实体范围闸（M-4，FP11 放宽开关默认 off）、配置新闻子串硬匹配（S5）、网页研究时间窗与无日期页面丢弃（S1）、代码替模型选读哪一段（S2–S4）、知识沉淀 `_SECRET` 电话正则误报日期（A1）、写授权否定窗口误报「别忘了」（M-7）、记忆兜底词表（P-1）。
- 修复范围与优先级待 owner 拍板，尚未立项。

## 生产拓扑（2026-11-13 时点）

- 后端跑在**黑豹 X2 盒**（RK3566 小盒）：API + Telegram bridge + sentinel + 本地 PostgreSQL（权威数据源）；前端在 GitHub Pages。
- 盒上源码不是 git 检出，发布走 **archive-swap**（整树替换 + 搬运 .env 与 data/ 运行时文件）。
- RAG 已迁回盒上：pgvector 存 6,026 条向量，瘦后端 `finbot-rag-slim` 在盒 127.0.0.1:8766；embedding（BAAI/bge-m3）2026-11-13 起走 OpenRouter（owner 拍板），rerank（BAAI/bge-reranker-v2-m3）走 SiliconFlow API。瘦后端**没有增量索引**，新入库文档不会自动进向量库。
- Supabase 只剩 2026-11-03 迁移时的冻结回滚副本，生产不依赖它。

## 模型与核查（盒上 catalog，2026-11-13 时点）

- 默认对话模型 `haiku-5.5`（OpenRouter，owner 自选）；另有 `muse-ember`、`gpt-6.1-terra`（OpenRouter）。
- 模型政策（owner 2026-11-13）：停用 DeepSeek 与 GLM，全面转向 Haiku 与 Ember；法官影子通道 = `muse-ember`（CLAIM_JUDGE_SHADOW=on，公开 gate phase=auto）。
- 后台角色：earnings=muse-ember、forecast=gpt-6.1-terra（去留待 owner 定）。
- 旧数字核查线已停标：`CLAIM_NUMBER_REVIEW=off`（FP0，2026-11-11 上线）——它不再改答案状态、不加脚注、不删句；对外可见的核查标注只走法官的统一公门。

## 协作分工（owner 2026-11-17 更新）

- 规划和简报：Fable。Fable 额度不够时，日常规划改用 Opus，并告诉 owner。
- 实施：Sonnet（high）。
- 验收和裁定：Opus，在独立会话里做。以 git diff 为主，需要确认影响范围时只打开被改函数的调用方；结论附命令和输出。
- 高风险改动（金额和数字计算、密钥与鉴权、数据迁移、生产发布）：验收改用 Fable。

## 活文档在哪

- Fable 5.2 实施方案（FP0–FP13）、D-F0–F7 裁定、验收报告与实时进度：不在仓库，在操作员（Daniel）的工作区，需要时问 Daniel，不要凭本文件猜进度。
- 本仓库 `docs/` 其余文件多为各阶段施工图与验收报告，是历史技术文档，不是路线图。

## 私有同步仓库（owner 2026-11-17 拍板建立）

- 两边 Claude 的**完整**记忆、进度快照与对话记录原文同步在私有仓库 `wp1461772181-glitch/claude-sync`（本仓库是公开的，只放本文件这样的筛选版）。查另一边机器的记忆或历史对话，先去那里找：`vm/`、`mac/` 是两边的记忆，`progress/` 是进度快照，`conversations/<vm|mac>/<项目>/` 是对话原文（`.jsonl.gz`，解压后搜）。
- 规矩：各写各的目录；`shared/` 由操作员维护；密钥与凭证绝不进仓库（细则在该仓库 README）。
