#!/bin/bash
# Move AUBOT's database from Render to the AWS host.
#
#   deploy/aws/migrate-from-render.sh backup          Save a copy of the Render database on this Mac
#                                                     (needs pg_dump 18: brew install postgresql@18)
#   deploy/aws/migrate-from-render.sh restore [FILE]  Load a saved copy into the AWS host
#                                                     (default: the newest file in deploy/aws/backups/)
#   deploy/aws/migrate-from-render.sh direct          Copy straight from Render to AWS; the dump runs
#                                                     on the server, so nothing is needed on this Mac
#
# You'll be asked for Render's *External Database URL* (Render -> aubot-db -> Connect -> External).
# It's read without echoing and never written to disk or into your shell history.
# Restoring replaces everything in the AWS database, including the staff accounts deploy.sh created:
# afterwards the staff passwords are the ones from Render.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BACKUPS="$HERE/backups"
COMPOSE="docker compose -f deploy/aws/docker-compose.prod.yml --env-file .env.prod"

ask_url() {
  read -rsp "Render External Database URL: " RENDER_URL; echo
  case "$RENDER_URL" in
    postgres://*|postgresql://*) ;;
    *) echo "That doesn't look like a postgres:// URL." >&2; exit 1 ;;
  esac
}

connect_aws() {
  [ -f "$HERE/.state" ] || { echo "No AWS host yet: run deploy/aws/provision.sh and deploy.sh first." >&2; exit 1; }
  source "$HERE/.state"
  SSH="ssh -i $KEY_FILE -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 ec2-user@$IP"
}

# Reads a custom-format dump on stdin and loads it with the web app stopped, so nothing writes mid-restore.
restore_on_server() {
  $SSH "cd /opt/aubot && $COMPOSE stop web >/dev/null && \
    $COMPOSE exec -T db pg_restore -U aubot -d aubot --clean --if-exists --no-owner --no-acl --exit-on-error; \
    status=\$?; $COMPOSE start web >/dev/null; exit \$status"
}

case "${1:-}" in
  backup)
    major=$(pg_dump --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')
    if [ "$major" -lt 18 ]; then
      echo "pg_dump $major is too old for Render's Postgres 18. Install the newer one, then re-run:" >&2
      echo "  brew install postgresql@18 && export PATH=\"$(brew --prefix 2>/dev/null || echo /opt/homebrew)/opt/postgresql@18/bin:\$PATH\"" >&2
      exit 1
    fi
    ask_url
    mkdir -p "$BACKUPS"
    FILE="$BACKUPS/render-$(date +%Y%m%d-%H%M%S).dump"
    pg_dump --dbname="$RENDER_URL" -Fc --no-owner --no-acl -f "$FILE"
    chmod 600 "$FILE"
    echo "Saved $(du -h "$FILE" | cut -f1) to $FILE"
    ;;

  restore)
    FILE=${2:-$(ls -t "$BACKUPS"/*.dump 2>/dev/null | head -1 || true)}
    [ -n "$FILE" ] && [ -f "$FILE" ] || { echo "No dump file found; run '$0 backup' first or pass a file." >&2; exit 1; }
    connect_aws
    echo "Restoring $FILE into https://$DOMAIN …"
    restore_on_server < "$FILE"
    echo "Done: https://$DOMAIN/staff (log in with your Render staff passwords)"
    ;;

  direct)
    connect_aws
    ask_url
    echo "Copying Render's database into https://$DOMAIN …"
    # The URL goes over SSH on stdin; the server dumps with its own pg_dump 18 and restores in one pipe.
    printf '%s\n' "$RENDER_URL" | $SSH "cd /opt/aubot && read -r URL && \
      $COMPOSE exec -T db pg_dump --dbname=\"\$URL\" -Fc --no-owner --no-acl" | restore_on_server
    echo "Done: https://$DOMAIN/staff (log in with your Render staff passwords)"
    ;;

  *)
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
