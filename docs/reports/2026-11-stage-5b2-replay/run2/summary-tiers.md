# 哨兵回放（tiers，standard）

命令：`python -m scripts.sentinel_replay --symbols INTC,AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD --snapshot docs/reports/2026-11-stage-5b2-replay/run2/snapshot.json --from 2026-11-03 --to 2026-11-25 --cache /private/tmp/claude-501/-Users-wupeng--claude-spares-spare-5lHNoF/da47914c-6a5b-4ebd-8120-ac05d9527de4/scratchpad/r5b2/bars.json --out docs/reports/2026-11-stage-5b2-replay/run2`

- 发出 60 条；夜间简报行（不到档、过 1 倍日常波动）96 条

| 股票 | 条数 |
|---|---|
| * | 4 |
| AAPL | 7 |
| AMD | 5 |
| GOOGL | 3 |
| INTC | 7 |
| META | 6 |
| MSFT | 4 |
| NVDA | 18 |
| TSLA | 6 |

| 档位 | 条数 |
|---|---|
| 1 | 48 |
| 2 | 12 |

| 系统默认规则 | 条数 |
|---|---|
| concentration | 2 |
| down_streak | 4 |
| new_high_52w | 2 |
| new_low_52w | 2 |
| portfolio_drawdown | 4 |
| volume_surge | 1 |

说明：
- 持仓和计划取自 snapshot.json（回放用的快照，不是当时的真实快照）
- 回放没有套用夜间规则（北京时间 0 点到 8 点），实际会进简报的提醒也列在里面
