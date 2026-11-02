#!/bin/bash
# Repeatable Mac-Postgres -> Supabase migration, driven from the Muse VM. Safe on the Mac: read-only pg_dump.
#   scripts/migrate_to_supabase.sh dump      # Mac docker pg_dump -Fc over ssh -> $DUMP
#   scripts/migrate_to_supabase.sh restore   # pg_restore into Supabase (via local tunnel, DATABASE_URL_DIRECT)
#   scripts/migrate_to_supabase.sh counts    # exact row counts of public tables, Mac vs Supabase, diff
#   scripts/migrate_to_supabase.sh all       # dump + restore + RLS + counts
# For the real cutover: stop the Mac writers first (plan 4.5), then run `all`.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MAC_SSH="${MAC_SSH:-$HOME/workspace/tools/mac-ssh}"
OUT="${FINBOT_DATA_DIR:-$HOME/finbot-data}/backups"
DUMP="${DUMP:-$OUT/finbot-latest.dump}"
PGBIN="${PGBIN:-$ROOT/.local/venv/lib/python3.12/site-packages/pgserver/pginstall/bin}"
export PGCONNECT_TIMEOUT=15
MACENV='export PATH=/opt/homebrew/bin:$HOME/.orbstack/bin:$PATH; '
MAC_PSQL="docker exec -i market-evidence-postgres psql -U market_evidence -d market_evidence"
COUNT_SQL="select table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by 1"

target_url() { # libpq URL through the local tunnel; never printed
    sed -n 's/^DATABASE_URL_DIRECT=//p' "$ROOT/.local/supabase-conn.txt" | sed 's#@db\.[^:/]*:5432#@127.0.0.1:15432#'
}
dump() {
    mkdir -p "$OUT"; umask 077
    "$MAC_SSH" "$MACENV docker exec market-evidence-postgres pg_dump -U market_evidence -Fc --no-owner --no-privileges market_evidence" > "$DUMP.part"
    mv "$DUMP.part" "$DUMP"; ls -l "$DUMP" | awk '{print "dump bytes:", $5}'
}
restore() {
    "$PGBIN/pg_restore" --clean --if-exists --no-owner --no-privileges --exit-on-error -d "$(target_url)" "$DUMP"
}
counts() {
    "$MAC_SSH" "$MACENV $MAC_PSQL -AtF'|' -c \"$COUNT_SQL\"" > "$OUT/counts-mac.txt"
    "$PGBIN/psql" "$(target_url)" -AtF'|' -c "$COUNT_SQL" > "$OUT/counts-supabase.txt"
    wc -l < "$OUT/counts-mac.txt" | awk '{print "tables on Mac:", $1}'
    if diff -u "$OUT/counts-mac.txt" "$OUT/counts-supabase.txt"; then echo "ROW COUNTS MATCH"; else echo "ROW COUNTS DIFFER" >&2; return 1; fi
    "$PGBIN/psql" "$(target_url)" -Atc "select 'supabase db size: '||pg_size_pretty(pg_database_size(current_database()))"
    "$MAC_SSH" "$MACENV $MAC_PSQL -Atc \"select 'mac db size: '||pg_size_pretty(pg_database_size(current_database()))\""
}
case "${1:-}" in
    dump) dump ;;
    restore) restore ;;
    counts) counts ;;
    all) dump; restore; "$ROOT/scripts/supabase_lockdown.sh"; counts ;;
    *) echo "usage: $0 dump|restore|counts|all" >&2; exit 2 ;;
esac
