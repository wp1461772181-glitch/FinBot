# 哨兵回放（tiers，standard）

命令：`python -m scripts.sentinel_replay --symbols INTC,AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD --snapshot docs/reports/2026-11-stage-5a-replay/snapshot.json --from 2026-11-03 --to 2026-11-25 --policy tiers --cache /private/tmp/claude-501/-Users-wupeng--claude-spares-spare-5lHNoF/da47914c-6a5b-4ebd-8120-ac05d9527de4/scratchpad/bars.json --out docs/reports/2026-11-stage-5a-replay`

- 发出 45 条；夜间简报行（不到档、过 1 倍日常波动）96 条

| 股票 | 条数 |
|---|---|
| AAPL | 4 |
| AMD | 5 |
| GOOGL | 2 |
| INTC | 6 |
| META | 5 |
| MSFT | 2 |
| NVDA | 15 |
| NVDA+TSLA | 1 |
| TSLA | 5 |

| 档位 | 条数 |
|---|---|
| 1 | 36 |
| 2 | 9 |

说明：
- 持仓和计划取自 snapshot.json（回放用的快照，不是当时的真实快照）
- 回放没有套用夜间规则（北京时间 0 点到 8 点），实际会进简报的提醒也列在里面
