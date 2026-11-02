#!/bin/bash
# Apply scripts/supabase_lockdown.sql to Supabase (via the local tunnel) and verify. Safe to re-run.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PGBIN="${PGBIN:-$ROOT/.local/venv/lib/python3.12/site-packages/pgserver/pginstall/bin}"
URL=$(sed -n 's/^DATABASE_URL_DIRECT=//p' "$ROOT/.local/supabase-conn.txt" | sed 's#@db\.[^:/]*:5432#@127.0.0.1:15432#')
export PGCONNECT_TIMEOUT=15
"$PGBIN/psql" "$URL" -v ON_ERROR_STOP=1 -q -f "$ROOT/scripts/supabase_lockdown.sql"
"$PGBIN/psql" "$URL" -At -v ON_ERROR_STOP=1 <<'SQL'
select 'public tables: '||count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p');
select 'tables WITHOUT rls: '||count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p') and not c.relrowsecurity;
select 'tables still granted to anon/authenticated: '||count(*) from information_schema.role_table_grants where table_schema='public' and grantee in ('anon','authenticated');
select 'app role '||current_user||' can read: '||has_table_privilege(current_user, c.oid, 'SELECT') from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' limit 1;
SQL
