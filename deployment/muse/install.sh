#!/bin/sh
# Install the FinBot systemd units on the Muse VM (run as root).
#   deployment/muse/install.sh            # write env files + install units, enable + start ONLY the two tunnels
#   deployment/muse/install.sh --cutover  # additionally enable + start finbot-api and finbot-telegram
# Secrets: /etc/finbot/proxy.env is written from the current HTTPS_PROXY (never printed);
# /etc/finbot/muse.env holds DATABASE_URL (from .local/supabase-conn.txt, pointed at the local tunnel),
# RAG_REMOTE_URL / RAG_REMOTE_TOKEN and BACKGROUND_LOOPS. Re-run after the proxy credential changes.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
CONN="$ROOT/.local/supabase-conn.txt"
DATA="${FINBOT_DATA_DIR:-/home/hatch/finbot-data}"
umask 077
mkdir -p /etc/finbot "$DATA/config"
[ -n "${HTTPS_PROXY:-}" ] || { echo "HTTPS_PROXY is not set" >&2; exit 1; }
printf 'HTTPS_PROXY=%s\n' "$HTTPS_PROXY" > /etc/finbot/proxy.env
if [ ! -f /etc/finbot/muse.env ]; then
    DB=$(sed -n 's/^DATABASE_URL_DIRECT=//p' "$CONN" | sed -e 's#^postgresql://#postgresql+psycopg://#' -e 's#@db\.[^:/]*:5432#@127.0.0.1:15432#')
    [ -n "$DB" ] || { echo "DATABASE_URL_DIRECT not found in $CONN" >&2; exit 1; }
    {
        printf 'DATABASE_URL=%s\n' "$DB"
        printf 'RAG_ENABLED=true\nRAG_REMOTE_URL=http://127.0.0.1:18765\nRAG_REMOTE_TOKEN=CHANGE_ME\n'
        printf 'RAG_INDEXING_ENABLED=false\nBACKGROUND_LOOPS=true\n'
        printf 'FINBOT_NEWS_SOURCES_CONFIG=%s/config/news_sources.yaml\n' "$DATA"
        for k in TAVILY_API_KEY SEC_EDGAR_USER_AGENT; do
            v=$(grep -E "^$k=" "$ROOT/.env" 2>/dev/null | head -n 1 | cut -d= -f2- || true)
            if [ -n "$v" ]; then printf '%s=%s\n' "$k" "$v"; fi
        done
    } > /etc/finbot/muse.env
    echo "wrote /etc/finbot/muse.env — set RAG_REMOTE_TOKEN to the same value as on the Mac"
fi
[ -f "$DATA/config/news_sources.yaml" ] || cp "$ROOT/config/news_sources.yaml" "$DATA/config/news_sources.yaml"
for u in finbot-tunnel-db finbot-tunnel-mac finbot-api finbot-telegram; do
    install -m 644 "$ROOT/deployment/muse/systemd/$u.service" "/etc/systemd/system/$u.service"
done
systemctl daemon-reload
systemctl enable --now finbot-tunnel-db finbot-tunnel-mac
if [ "${1:-}" = "--cutover" ]; then
    systemctl enable --now finbot-api finbot-telegram
else
    echo "units installed; finbot-api and finbot-telegram NOT started (use --cutover at switch time)"
fi
