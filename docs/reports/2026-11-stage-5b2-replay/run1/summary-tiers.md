# 哨兵回放（tiers，standard）

命令：`python -m scripts.sentinel_replay --symbols INTC,AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD --snapshot docs/reports/2026-11-stage-5b2-replay/snapshot-1.json --from 2026-11-03 --to 2026-11-25 --cache /private/tmp/claude-501/-Users-wupeng--claude-spares-spare-5lHNoF/da47914c-6a5b-4ebd-8120-ac05d9527de4/scratchpad/r5b2/bars.json --out docs/reports/2026-11-stage-5b2-replay/run1`

- 发出 77 条；夜间简报行（不到档、过 1 倍日常波动）96 条

| 股票 | 条数 |
|---|---|
| * | 7 |
| AAPL | 13 |
| AMD | 5 |
| GOOGL | 5 |
| INTC | 8 |
| META | 6 |
| MSFT | 5 |
| NVDA | 22 |
| NVDA+TSLA | 1 |
| TSLA | 5 |

| 档位 | 条数 |
|---|---|
| 1 | 66 |
| 2 | 11 |

| 系统默认规则 | 条数 |
|---|---|
| concentration | 1 |
| down_streak | 4 |
| new_high_52w | 11 |
| new_low_52w | 9 |
| portfolio_drawdown | 7 |

说明：
- 持仓和计划取自 snapshot-1.json（回放用的快照，不是当时的真实快照）
- 回放没有套用夜间规则（北京时间 0 点到 8 点），实际会进简报的提醒也列在里面
