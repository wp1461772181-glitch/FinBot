#!/usr/bin/env bash
# Release a merged commit to the heibao box by archive-swap, in one command (docs/finbot-humanlike-plan-2026-11-28, section 8 item 2).
#
#   deployment/heibao/release.sh [<git ref>]      # default origin/main; run from a checkout of this repository
#
# What it does, in order, stopping at the first failure:
#   1. the ref must be on origin/main (only merged code is released) and the box must answer;
#   2. back up the database (/opt/finbot/bin/finbot-db-backup.sh with /opt/finbot/backup.env);
#   3. upload `git archive <ref>` to /opt/finbot/incoming-<sha>.tar.gz and unpack it into /opt/finbot/src-new;
#   4. stop telegram, wechat, sentinel and the API; move src to the next free src-oldNNN; move src-new to src; carry .env and data/ over;
#   5. start the API and wait for /health (3 minutes).  If it does not come up, put the old tree back, start everything again and exit 1;
#   6. start the other three and print each service's state.
# It never touches boot settings, mounts, the network or Tailscale.  Stopping is by service name (systemctl), never pkill.
set -euo pipefail

REF="${1:-origin/main}"
HOST="${HEIBAO_HOST:-heibao-ts}"
ROOT=/opt/finbot
OTHERS="finbot-telegram finbot-wechat finbot-sentinel"

git fetch -q origin
SHA="$(git rev-parse --short "$REF")"
git merge-base --is-ancestor "$SHA" origin/main || { echo "release: $SHA is not on origin/main" >&2; exit 1; }
ssh -n -o ConnectTimeout=10 "$HOST" true || { echo "release: $HOST does not answer" >&2; exit 1; }
echo "release: $SHA to $HOST"

ssh -n "$HOST" "sudo bash -c 'set -a; . $ROOT/backup.env; set +a; $ROOT/bin/finbot-db-backup.sh' 2>&1 | tail -1"
BACKUP="$(ssh -n "$HOST" "ls -t $ROOT/backups/db | grep '^finbot-' | head -1")"
echo "release: backup $BACKUP"

git archive --format=tar.gz "$SHA" | ssh "$HOST" "sudo tee $ROOT/incoming-$SHA.tar.gz >/dev/null && sudo rm -rf $ROOT/src-new && sudo mkdir $ROOT/src-new && sudo tar -xzf $ROOT/incoming-$SHA.tar.gz -C $ROOT/src-new && test -f $ROOT/src-new/app/main.py"

# shellcheck disable=SC2087  # the remote script is meant to expand there
ssh "$HOST" "sudo bash -s" <<REMOTE
set -u
cd $ROOT
last=\$(ls -d src-old* 2>/dev/null | sed 's/src-old//' | grep -E '^[0-9]+$' | sort -n | tail -1)
OLD=src-old\$(( \${last:-0} + 1 ))
health() { for i in \$(seq 1 60); do c=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health || true); [ "\$c" = "200" ] && return 0; sleep 3; done; return 1; }
systemctl stop $OTHERS finbot-api || true
mv src \$OLD && mv src-new src && cp -a \$OLD/.env src/.env && rsync -a \$OLD/data/ src/data/ || { echo "release: swap failed"; exit 1; }
systemctl start finbot-api || true
if ! health; then
  echo "release: the API did not come up; putting \$OLD back"
  systemctl stop finbot-api || true
  mv src src-failed-$SHA && mv \$OLD src
  systemctl start finbot-api || true
  health && echo "release: the old tree is serving again" || echo "release: the old tree did not come up either"
  systemctl start $OTHERS || true
  exit 1
fi
systemctl start $OTHERS || true
sleep 6
for s in finbot-api $OTHERS finbot-rag-slim; do echo "\$s \$(systemctl is-active \$s)"; done
echo "release: $SHA is live; the previous tree is $ROOT/\$OLD"
REMOTE
