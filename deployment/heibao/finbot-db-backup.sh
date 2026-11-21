#!/usr/bin/env bash
# FinBot 数据库每日备份（黑豹盒子，root 运行，由 finbot-db-backup.timer 触发）。
# 主库 finbot-postgres 必备；向量库 finbot-pgvector 仅在配置了
# PGVECTOR_DB_USER / PGVECTOR_DB_NAME 时备份。不打印、不落盘任何密码。
set -euo pipefail

ENV_FILE="${FINBOT_ENV_FILE:-/opt/finbot/src/.env}"
PG_CONTAINER="${PG_CONTAINER:-finbot-postgres}"
PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER:-finbot-pgvector}"
BACKUP_DIR="${BACKUP_DIR:-/opt/finbot/backups/db}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
BACKUP_MIN_BYTES="${BACKUP_MIN_BYTES:-1048576}"   # 1 MB
BACKUP_MIN_FREE_MB="${BACKUP_MIN_FREE_MB:-2048}"  # 2 GB

FAIL_MSG=""
PARTIAL=""

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

notify_failure() {
  local msg="$1"
  if [ -n "${BACKUP_ALERT_CMD:-}" ]; then
    # 通知失败不影响退出码；消息作为第一个参数传入
    sh -c "$BACKUP_ALERT_CMD \"\$1\"" _ "$msg" || log "失败通知命令执行出错（已忽略）"
  fi
}

on_exit() {
  local rc=$?
  if [ -n "$PARTIAL" ]; then
    rm -f -- "$PARTIAL"
  fi
  if [ "$rc" -ne 0 ]; then
    [ -n "$FAIL_MSG" ] || FAIL_MSG="备份脚本异常退出（退出码 ${rc}）"
    log "失败：$FAIL_MSG"
    notify_failure "FinBot 数据库备份失败：$FAIL_MSG"
  fi
}
trap on_exit EXIT

die() { FAIL_MSG="$1"; exit 1; }

case "$BACKUP_KEEP" in ''|*[!0-9]*) die "BACKUP_KEEP 必须是正整数" ;; esac
[ "$BACKUP_KEEP" -ge 1 ] || die "BACKUP_KEEP 必须 >= 1"
[ -n "$BACKUP_DIR" ] || die "BACKUP_DIR 为空"

# 从 DATABASE_URL 取用户名、库名（不 source .env，不取密码）
[ -r "$ENV_FILE" ] || die "读不到 $ENV_FILE"
url="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DATABASE_URL=' "$ENV_FILE" | tail -n 1 || true)"
[ -n "$url" ] || die "$ENV_FILE 里没有 DATABASE_URL"
url="${url#*=}"
url="${url%\"}"; url="${url#\"}"; url="${url%\'}"; url="${url#\'}"
case "$url" in *://*) ;; *) die "DATABASE_URL 格式无法解析" ;; esac
rest="${url#*://}"
case "$rest" in *@*) ;; *) die "DATABASE_URL 缺少用户信息" ;; esac
userinfo="${rest%@*}"
hostpart="${rest##*@}"
PG_USER="${userinfo%%:*}"
case "$hostpart" in */*) PG_DB="${hostpart#*/}" ;; *) PG_DB="" ;; esac
PG_DB="${PG_DB%%\?*}"
unset url rest userinfo hostpart
[ -n "$PG_USER" ] || die "DATABASE_URL 解析不出用户名"
[ -n "$PG_DB" ] || die "DATABASE_URL 解析不出库名"

command -v docker >/dev/null 2>&1 || die "找不到 docker 命令"

mkdir -p -- "$BACKUP_DIR"
chmod -- 700 "$BACKUP_DIR"

# 磁盘保护（df -Pk 在 GNU 与 BSD 上输出格式一致）
avail_kb="$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
case "$avail_kb" in ''|*[!0-9]*) die "读不到备份目录可用空间" ;; esac
if [ $((avail_kb / 1024)) -lt "$BACKUP_MIN_FREE_MB" ]; then
  die "备份目录可用空间 $((avail_kb / 1024)) MB，低于阈值 ${BACKUP_MIN_FREE_MB} MB，已放弃备份"
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
OK_FILES=()

# 备份一个容器：backup_one 前缀 容器 用户 库名
backup_one() {
  local prefix="$1" container="$2" user="$3" db="$4"
  local final="$BACKUP_DIR/${prefix}-${STAMP}.dump"
  local size
  PARTIAL="$final.partial"
  umask 077
  log "开始备份 $container -> $(basename "$final")"
  if ! docker exec "$container" pg_dump -U "$user" -d "$db" -Fc > "$PARTIAL"; then
    FAIL_MSG="$container 的 pg_dump 失败"; return 1
  fi
  size="$(wc -c < "$PARTIAL" | tr -d '[:space:]')"
  if [ "$size" -le "$BACKUP_MIN_BYTES" ]; then
    FAIL_MSG="$container 备份只有 ${size} 字节，小于最小值 ${BACKUP_MIN_BYTES}"; return 1
  fi
  if ! docker exec -i "$container" pg_restore --list < "$PARTIAL" > /dev/null; then
    FAIL_MSG="$container 备份文件校验失败（pg_restore --list 读不了）"; return 1
  fi
  chmod -- 600 "$PARTIAL"
  mv -- "$PARTIAL" "$final"
  PARTIAL=""
  log "完成 $(basename "$final")，${size} 字节，校验通过"
  OK_FILES+=("$(basename "$final") $size")
  return 0
}

# 只清理 BACKUP_DIR 内、本脚本自己命名模式的文件；
# 文件名含 UTC 时间戳，按名字排序即按时间排序，保留最近 BACKUP_KEEP 份
prune() {
  local prefix="$1" f i total remove
  local files=()
  shopt -s nullglob
  for f in "$BACKUP_DIR/${prefix}"-*.dump; do
    files+=("$f")
  done
  shopt -u nullglob
  total=${#files[@]}
  [ "$total" -gt "$BACKUP_KEEP" ] || return 0
  remove=$((total - BACKUP_KEEP))
  for ((i = 0; i < remove; i++)); do
    log "清理旧备份 $(basename "${files[$i]}")"
    rm -f -- "${files[$i]}"
  done
}

backup_one finbot "$PG_CONTAINER" "$PG_USER" "$PG_DB" || exit 1
prune finbot

if [ -n "${PGVECTOR_DB_USER:-}" ] && [ -n "${PGVECTOR_DB_NAME:-}" ]; then
  backup_one pgvector "$PGVECTOR_CONTAINER" "$PGVECTOR_DB_USER" "$PGVECTOR_DB_NAME" || exit 1
  prune pgvector
else
  log "向量库未配置，已跳过（需要 PGVECTOR_DB_USER 与 PGVECTOR_DB_NAME）"
fi

STATUS_TMP="$BACKUP_DIR/last-success.txt.tmp"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
for item in "${OK_FILES[@]}"; do
  printf '%s %s %s 字节\n' "$now" "${item% *}" "${item##* }"
done > "$STATUS_TMP"
chmod -- 600 "$STATUS_TMP"
mv -- "$STATUS_TMP" "$BACKUP_DIR/last-success.txt"
log "全部完成"
