#!/usr/bin/env bash
# Shadow environment for the ruler (evaluation harness) on the heibao box.  Run as root on the box.
#
#   ruler_shadow.sh up      restore the newest nightly backup into database finbot_ruler, copy the live source
#                           tree (with its data/ and .env) to /opt/finbot/ruler-src, start a second API on :9031
#   ruler_shadow.sh status  what exists and what is running
#   ruler_shadow.sh down    stop the shadow API, drop finbot_ruler, remove the copy
#
# The shadow API reads and writes only finbot_ruler and its own copy of data/, with background loops off, so an
# evaluation run leaves the live conversations, memory, outbox and sentinel snapshot untouched.  The database
# password is never printed: the shadow DATABASE_URL goes into a root-only env file.
set -euo pipefail

LIVE_SRC="${LIVE_SRC:-/opt/finbot/src}"
SHADOW_SRC="${SHADOW_SRC:-/opt/finbot/ruler-src}"
SHADOW_ENV="${SHADOW_ENV:-/opt/finbot/ruler.env}"
SHADOW_DB="finbot_ruler"
SHADOW_PORT="${SHADOW_PORT:-9031}"
UNIT="finbot-ruler-api"
PG_CONTAINER="${PG_CONTAINER:-finbot-postgres}"
BACKUP_DIR="${BACKUP_DIR:-/opt/finbot/backups/db}"
MIN_FREE_MB="${MIN_FREE_MB:-800}"
MARK="/opt/finbot/ruler-shadow.source"

die() { echo "ruler_shadow: $*" >&2; exit 1; }

database_url() {
  local line
  line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?DATABASE_URL=' "$LIVE_SRC/.env" | tail -n 1 || true)"
  [ -n "$line" ] || die "no DATABASE_URL in $LIVE_SRC/.env"
  line="${line#*=}"; line="${line%\"}"; line="${line#\"}"; line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

# user and live database name from the URL (never the password)
parse_url() {
  local url rest userinfo hostpart
  url="$(database_url)"; rest="${url#*://}"
  userinfo="${rest%@*}"; hostpart="${rest##*@}"
  PG_USER="${userinfo%%:*}"
  LIVE_DB="${hostpart#*/}"; LIVE_DB="${LIVE_DB%%\?*}"
  [ -n "$PG_USER" ] && [ -n "$LIVE_DB" ] || die "cannot parse DATABASE_URL"
  [ "$LIVE_DB" != "$SHADOW_DB" ] || die "the live database is named $SHADOW_DB; refusing"
}

psql_c() { docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -Atc "$1"; }

shadow_exists() { [ "$(psql_c "select 1 from pg_database where datname='$SHADOW_DB'")" = "1" ]; }

api_running() { systemctl is-active --quiet "$UNIT"; }

stop_api() { if api_running; then systemctl stop "$UNIT"; fi; systemctl reset-failed "$UNIT" 2>/dev/null || true; }

up() {
  parse_url
  local free dump url shadow_url
  free="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)"
  [ "$free" -ge "$MIN_FREE_MB" ] || die "only ${free} MB available, need ${MIN_FREE_MB}"
  dump="$(ls -1t "$BACKUP_DIR"/"$LIVE_DB"-*.dump 2>/dev/null | head -n 1 || true)"
  [ -n "$dump" ] || die "no backup named $LIVE_DB-*.dump in $BACKUP_DIR"
  stop_api
  echo "restoring $(basename "$dump") into $SHADOW_DB ..."
  docker exec "$PG_CONTAINER" dropdb -U "$PG_USER" --if-exists --force "$SHADOW_DB"
  docker exec "$PG_CONTAINER" createdb -U "$PG_USER" "$SHADOW_DB"
  docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$SHADOW_DB" --no-owner --no-privileges < "$dump"
  basename "$dump" > "$MARK"

  rsync -a --delete --exclude '__pycache__' "$LIVE_SRC"/ "$SHADOW_SRC"/
  url="$(database_url)"
  shadow_url="${url%/"$LIVE_DB"*}/$SHADOW_DB"
  case "$url" in *\?*) shadow_url="$shadow_url?${url#*\?}" ;; esac
  ( umask 077; printf 'DATABASE_URL=%s\nBACKGROUND_LOOPS=false\nDB_POOL_SIZE=3\nDB_MAX_OVERFLOW=2\n' "$shadow_url" > "$SHADOW_ENV" )

  systemd-run --quiet --unit="$UNIT" --description="FinBot ruler shadow API" \
    -p WorkingDirectory="$SHADOW_SRC" -p MemoryMax=600M \
    -p EnvironmentFile=/opt/finbot/langfuse.env -p EnvironmentFile=/opt/finbot/sentinel-token.env \
    -p EnvironmentFile="$SHADOW_SRC/.env" -p EnvironmentFile="$SHADOW_ENV" \
    /opt/finbot/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$SHADOW_PORT"
  for _ in $(seq 1 40); do
    if curl -fsS -m 3 "http://127.0.0.1:$SHADOW_PORT/health" >/dev/null 2>&1; then
      echo "shadow API is up on :$SHADOW_PORT (database $SHADOW_DB, from $(cat "$MARK"))"; return 0
    fi
    sleep 3
  done
  die "shadow API did not answer /health; see: journalctl -u $UNIT"
}

status() {
  parse_url
  if shadow_exists; then echo "database: $SHADOW_DB exists (from $(cat "$MARK" 2>/dev/null || echo unknown))"; else echo "database: $SHADOW_DB absent"; fi
  if api_running; then echo "api: running on :$SHADOW_PORT"; else echo "api: stopped"; fi
  [ -d "$SHADOW_SRC" ] && echo "source copy: $SHADOW_SRC" || echo "source copy: absent"
}

down() {
  parse_url
  stop_api
  docker exec "$PG_CONTAINER" dropdb -U "$PG_USER" --if-exists --force "$SHADOW_DB"
  rm -f -- "$SHADOW_ENV" "$MARK"
  case "$SHADOW_SRC" in /opt/finbot/ruler-src) rm -rf -- "$SHADOW_SRC" ;; *) echo "left $SHADOW_SRC in place (non-default path)" ;; esac
  echo "shadow environment removed"
}

case "${1:-}" in
  up) up ;;
  status) status ;;
  down) down ;;
  *) die "usage: $0 up|status|down" ;;
esac
