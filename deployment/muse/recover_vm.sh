#!/bin/bash
# FinBot one-shot recovery after the Muse platform REPLACES this VM.
#
# Why: only the home directory survives a VM replacement. Everything in
# /etc (systemd units, /etc/finbot/*.env) is wiped, so all FinBot services
# are down until this script runs. First done manually 2026-11-02 (~45 min);
# this script is that procedure, sequenced. Idempotent: safe to re-run.
#
# Run as root from an interactive shell where HTTPS_PROXY is set (the
# platform injects it). Secrets are never printed: they move only through
# variables and 0600 files.
#   bash deployment/muse/recover_vm.sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
MUSE_ENV=/etc/finbot/muse.env
TOKEN_FILE="$ROOT/.local/sentinel-token.txt"
umask 077

[ -n "${HTTPS_PROXY:-}" ] || { echo "ERROR: HTTPS_PROXY is not set in this shell" >&2; exit 1; }

echo "== 1/6 base install (env files + tunnel/api/telegram units) =="
sh deployment/muse/install.sh --cutover

echo "== 2/6 complete /etc/finbot/muse.env =="
# Model egress proxy (hotfix 02780e0): model traffic must use the egress proxy.
if ! grep -q '^MODEL_EGRESS_PROXY=' "$MUSE_ENV"; then
    printf 'MODEL_EGRESS_PROXY=%s\n' "$HTTPS_PROXY" >> "$MUSE_ENV"
    echo "added MODEL_EGRESS_PROXY"
fi
# Sentinel token: persisted in the home dir so recovery reuses the same one.
if [ ! -f "$TOKEN_FILE" ] && grep -q '^SENTINEL_TOKEN=' "$MUSE_ENV"; then
    grep '^SENTINEL_TOKEN=' "$MUSE_ENV" | cut -d= -f2- > "$TOKEN_FILE"
fi
if [ ! -f "$TOKEN_FILE" ]; then
    openssl rand -hex 32 > "$TOKEN_FILE"
    echo "generated a new SENTINEL_TOKEN (persisted to .local/sentinel-token.txt)"
fi
chmod 600 "$TOKEN_FILE" 2>/dev/null || true
if ! grep -q '^SENTINEL_TOKEN=' "$MUSE_ENV"; then
    printf 'SENTINEL_TOKEN=%s\n' "$(cat "$TOKEN_FILE")" >> "$MUSE_ENV"
    echo "added SENTINEL_TOKEN"
fi
# RAG token must match the Mac retrieval service (install.sh writes a
# placeholder). Always re-sync from the Mac when reachable; idempotent.
PH=$(grep -o 'RAG_REMOTE_TOKEN=[A-Za-z_]*' deployment/muse/install.sh | head -1 | cut -d= -f2)
CUR=$(grep '^RAG_REMOTE_TOKEN=' "$MUSE_ENV" | head -1 | cut -d= -f2 || true)
TOK=$("$HOME/workspace/tools/mac-ssh" '/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:RAG_REMOTE_TOKEN" ~/Library/LaunchAgents/com.market-evidence-agent.retrieval.plist' 2>/dev/null || true)
if [ -n "$TOK" ]; then
    if [ "$TOK" != "$CUR" ]; then
        grep -v '^RAG_REMOTE_TOKEN=' "$MUSE_ENV" > /tmp/menv.$$
        printf 'RAG_REMOTE_TOKEN=%s\n' "$TOK" >> /tmp/menv.$$
        install -m 600 /tmp/menv.$$ "$MUSE_ENV"
        rm -f /tmp/menv.$$
        echo "RAG_REMOTE_TOKEN synced from the Mac"
    else
        echo "RAG_REMOTE_TOKEN already matches the Mac"
    fi
elif [ -z "$CUR" ] || [ "$CUR" = "$PH" ]; then
    echo "WARNING: RAG token is unset/placeholder and the Mac was unreachable;" >&2
    echo "         research answers will be degraded until it is synced." >&2
fi

echo "== 3/6 sentinel + tailscaled units (not covered by install.sh) =="
install -m 644 deployment/muse/systemd/finbot-sentinel.service /etc/systemd/system/finbot-sentinel.service
install -m 644 deployment/muse/systemd/tailscaled-full.service /etc/systemd/system/tailscaled-full.service
systemctl daemon-reload
systemctl enable --now finbot-sentinel tailscaled-full

echo "== 4/6 restart app services so they pick up the completed env =="
systemctl restart finbot-api finbot-telegram finbot-sentinel

echo "== 5/6 dev heartbeat (Task 0) =="
if ! pgrep -f 'heartbeat\.sh' >/dev/null; then
    (setsid nohup .local/heartbeat.sh >/dev/null 2>&1 &)
    echo "heartbeat relaunched"
else
    echo "heartbeat already running"
fi

echo "== 6/6 verify =="
systemctl is-active finbot-tunnel-db finbot-tunnel-mac finbot-api finbot-telegram finbot-sentinel tailscaled-full
for i in $(seq 1 48); do
    if curl -s -m 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then
        echo "API healthy after ~$((i*5))s: $(curl -s -m 3 http://127.0.0.1:8000/health)"
        break
    fi
    [ "$i" = 48 ] && { echo "ERROR: API not healthy after 240s" >&2; exit 1; }
    sleep 5
done
"$HOME/.local/bin/tailscale-full" --socket="$HOME/.local/share/tailscale/tailscaled.sock" status 2>/dev/null | head -1 || true
echo "RECOVERY COMPLETE (public Funnel may take a few more minutes to settle)"
