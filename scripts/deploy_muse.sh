#!/bin/sh
# Deploy a commit to the Muse VM: fetch, install deps (never requirements-rag.txt), restart, wait for /health;
# on failure go back to the previous sha. Usage: scripts/deploy_muse.sh <sha> [--dry-run]
set -eu
SHA="${1:?usage: deploy_muse.sh <sha> [--dry-run]}"
DRY="${2:-}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
HEALTH_URL="${FINBOT_HEALTH_URL:-http://127.0.0.1:8000/health}"
WAIT="${FINBOT_HEALTH_WAIT:-90}"
SERVICES="${FINBOT_SERVICES:-finbot-api finbot-telegram}"
run() { if [ "$DRY" = "--dry-run" ]; then echo "+ $*"; else "$@"; fi; }
PREV=$(git rev-parse HEAD)
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "tracked changes present; refusing to deploy" >&2; exit 1; }
git fetch -q origin
git rev-parse --verify -q "$SHA^{commit}" >/dev/null || { echo "unknown sha $SHA" >&2; exit 1; }

install_deps() {
    [ -x .venv/bin/python ] || run python3 -m venv .venv
    # requirements-rag.txt (torch etc.) stays on the Mac; the API talks to RAG_REMOTE_URL.
    run .venv/bin/python -m pip install -q -e .
}
restart_and_wait() {
    for s in $SERVICES; do run systemctl restart "$s"; done
    [ "$DRY" = "--dry-run" ] && return 0
    waited=0
    until curl -fsS -m 3 "$HEALTH_URL" >/dev/null 2>&1; do
        waited=$((waited + 2))
        [ "$waited" -lt "$WAIT" ] || return 1
        sleep 2
    done
}
echo "deploying $SHA (previous $PREV)"
run git checkout -q --detach "$SHA"
if install_deps && restart_and_wait; then
    echo "healthy at $SHA"
    exit 0
fi
echo "deploy of $SHA failed; rolling back to $PREV" >&2
run git checkout -q --detach "$PREV"
install_deps || true
restart_and_wait || echo "rollback is also unhealthy: check journalctl -u finbot-api" >&2
exit 1
