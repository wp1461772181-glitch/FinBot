# 黑豹盒子运维文件

| 文件 | 作用 |
| --- | --- |
| `finbot-db-backup.sh` | 每日备份：主库 `finbot-postgres`（必备）+ 向量库 `finbot-pgvector`（可选） |
| `finbot-db-backup.service` / `.timer` | systemd 单元；每天北京时间 15:30 左右触发（随机延迟最多 5 分钟，`Persistent=true`，关机错过会补跑） |
| `../../.github/workflows/box-watchdog.yml` | 盒子之外的宕机探测（见文末） |

## 备份

行为：`docker exec <容器> pg_dump -Fc` 写入 `/opt/finbot/backups/db/finbot-YYYYmmdd-HHMMSS.dump`（UTC 时间；向量库为 `pgvector-...dump`）。先写 `.partial`，用 `pg_restore --list` 校验可读且大于 1 MB 后才改成正式名；权限 600，目录 700。成功后才清理旧文件，只匹配 `finbot-*.dump` / `pgvector-*.dump`，默认各保留最近 14 份；目录里其它文件不动。可用空间低于 2 GB 时拒绝备份。成功状态写入 `last-success.txt`。密码不会被读取或输出（容器内走本地 socket）。

### 安装

```bash
install -d /opt/finbot/bin
install -m 755 finbot-db-backup.sh /opt/finbot/bin/finbot-db-backup.sh
install -m 644 finbot-db-backup.service finbot-db-backup.timer /etc/systemd/system/
```

可选覆盖项写在 `/opt/finbot/backup.env`（权限 600，`KEY=value` 格式，无需引号）：

```
PGVECTOR_DB_USER=<向量库用户>      # 两个都设了才备份向量库
PGVECTOR_DB_NAME=<向量库库名>
# BACKUP_KEEP=14  BACKUP_MIN_FREE_MB=2048  BACKUP_MIN_BYTES=1048576
# BACKUP_ALERT_CMD=/opt/finbot/bin/some-notify.sh   # 失败时调用，第一个参数是中文原因
```

向量库用户/库名在 `/opt/finbot/pgvector.env` 里（`POSTGRES_USER` / `POSTGRES_DB` 之类），抄过来即可。

```bash
systemctl daemon-reload
systemctl enable --now finbot-db-backup.timer
systemctl list-timers finbot-db-backup.timer
```

### 手动跑一次

```bash
systemctl start finbot-db-backup.service      # 同步执行，结束后看结果
journalctl -u finbot-db-backup.service -n 30 --no-pager
ls -l /opt/finbot/backups/db/ && cat /opt/finbot/backups/db/last-success.txt
```

### 从备份恢复

原则：先恢复到临时库验证，再决定是否切换，不要直接覆盖线上库。以下以主库为例（容器 `finbot-postgres`，`<用户>`、`<库名>` 同 `.env` 里的 `DATABASE_URL`）。

```bash
F=/opt/finbot/backups/db/finbot-YYYYmmdd-HHMMSS.dump

# 1. 恢复到临时库
docker exec finbot-postgres createdb -U <用户> finbot_restore_test
docker exec -i finbot-postgres pg_restore -U <用户> -d finbot_restore_test --no-owner < "$F"

# 2. 验证（表数量、关键表行数是否合理）
docker exec finbot-postgres psql -U <用户> -d finbot_restore_test -c '\dt'
docker exec finbot-postgres psql -U <用户> -d finbot_restore_test -c 'select count(*) from <某张关键表>;'

# 3. 确认无误后切换：先停服务，再把旧库改名留底、临时库改成正式名
systemctl stop finbot-api finbot-telegram finbot-sentinel   # 以盒子上实际的单元名为准
docker exec finbot-postgres psql -U <用户> -d postgres -c 'ALTER DATABASE <库名> RENAME TO <库名>_old;'
docker exec finbot-postgres psql -U <用户> -d postgres -c 'ALTER DATABASE finbot_restore_test RENAME TO <库名>;'
systemctl start finbot-api finbot-telegram finbot-sentinel

# 4. 观察一段时间确认正常后，再删掉 <库名>_old
```

改名要求没有活动连接；若提示库正在使用，先确认服务已停，必要时在 `postgres` 库里 `pg_terminate_backend` 残留连接。向量库同理，换成 `finbot-pgvector` 容器与 `pgvector-*.dump`。

### 风险：备份只在盒子本机

备份与数据库在同一块盘上。盘坏、盒子被偷、误 `rm -rf` 时，备份和原库一起没了。需要另外把 `/opt/finbot/backups/db/` 定期拷到别的机器（如 `rsync` 到 Mac 或云盘），本目录不负责这一步。

## 宕机探测（box-watchdog）

GitHub Actions 每 15 分钟（UTC cron `*/15 * * * *`）从公网访问 `${{ vars.VITE_API_BASE_URL }}/health`：单次超时 15 秒，失败则隔 60 秒重试，3 次都失败才算宕机。它测的是「公网入口到后端 API 是否通」，不区分盒子断电、断网、Tailscale Funnel 故障或 API 进程挂掉。

- 宕机时：本次运行以失败结束（GitHub 给仓库主人发失败邮件）；若配置了 Telegram，同一次宕机只发一条，恢复后发一条「已恢复」。状态用 `actions/cache` 记录，缓存被 GitHub 清理（7 天无访问）时最坏情况是重复提醒一次。宕机期间每 15 分钟仍会有一次失败运行和失败邮件，这是 GitHub 侧行为。
- 延迟：GitHub 的定时任务不保证准点，常晚几分钟，繁忙时可晚几十分钟；加上 3 次重试约 2 分钟，实际发现宕机通常需要 15 到 40 分钟，不要当作秒级监控。
- 配置 Telegram（可选）：仓库 Settings → Secrets and variables → Actions → New repository secret，添加 `WATCHDOG_TELEGRAM_BOT_TOKEN`（Bot 令牌）和 `WATCHDOG_TELEGRAM_CHAT_ID`（接收消息的 chat id）。建议用与盒子上 bridge 不同的 bot，且先给该 bot 发过消息。没配置时只靠失败邮件。
- 限制：公开仓库连续 60 天没有提交时，GitHub 会自动停用定时工作流（会发邮件提示），需要在 Actions 页面手动重新启用，或推一次提交。
- 手动试跑：Actions 页面选 Box watchdog，Run workflow。

## 盒外副本（Mac）

盒子上的备份和数据库在同一块存储上，盘坏了两者一起丢。owner 的 Mac 上有一个 launchd 任务
`com.market-evidence-agent.backup`（脚本 `~/finbot-backup/backup.sh`，每天 20:00，Mac 睡着时醒来后补跑），
经 ssh 从盒子的 `/opt/finbot/backups/db/` 拉最新的 `finbot-*.dump` 和 `pgvector-*.dump` 到仓库的
`data/backups/`（已被 git 忽略），核对 sha256，各保留最近 7 份。日志在 `~/finbot-backup/backup.log`。
这个脚本不在仓库里；它之前是每周 pg_dump 已冻结的 Supabase 副本，2026-11-21 改为从盒子拉取。
