#!/bin/bash
# Ship the committed code to the EC2 host and (re)start AUBOT:  deploy/aws/deploy.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
source "$HERE/.state"
SSH="ssh -i $KEY_FILE -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 ec2-user@$IP"

echo "Waiting for SSH and first-boot setup…"
for i in $(seq 1 60); do $SSH 'test -f /var/lib/cloud/instance/aubot-ready' 2>/dev/null && break; sleep 10; done

echo "Uploading committed code ($(git -C "$ROOT" rev-parse --short HEAD))…"
git -C "$ROOT" archive --format=tar HEAD | $SSH 'tar -x -C /opt/aubot'

# Secrets are generated on the server and never committed. The OpenAI key travels over SSH
# into a 0600 temp file (not a command-line argument) and is deleted after use.
OPENAI_KEY=$(grep '^OPENAI_API_KEY=' "$ROOT/.env" | cut -d= -f2- || true)
printf '%s' "$OPENAI_KEY" | $SSH 'umask 077 && cat > /opt/aubot/.openai_key'
$SSH "DOMAIN=$DOMAIN BUCKET=$BUCKET bash -s" <<'REMOTE'
set -euo pipefail
cd /opt/aubot
KEY=$(cat .openai_key) && rm -f .openai_key
if [ ! -f .env.prod ]; then
  umask 077
  cat > .env.prod <<ENV
AUBOT_DOMAIN=$DOMAIN
BACKUP_BUCKET=$BUCKET
DJANGO_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')
POSTGRES_PASSWORD=$(openssl rand -hex 24)
OPENAI_API_KEY=$KEY
AUBOT_MONTHLY_BUDGET_USD=20
ENV
fi
# Keep the server's key in sync with your local .env.
if [ -n "$KEY" ]; then sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=$KEY|" .env.prod; fi
REMOTE

echo "Building and starting containers (first build takes several minutes on t3.micro)…"
$SSH 'cd /opt/aubot && docker compose -f deploy/aws/docker-compose.prod.yml --env-file .env.prod up -d --build --remove-orphans && docker image prune -f >/dev/null'

echo "Installing nightly backup timer…"
$SSH 'sudo tee /etc/systemd/system/aubot-backup.service >/dev/null <<UNIT
[Unit]
Description=AUBOT PostgreSQL backup to S3
[Service]
Type=oneshot
ExecStart=/opt/aubot/deploy/aws/backup.sh
UNIT
sudo tee /etc/systemd/system/aubot-backup.timer >/dev/null <<UNIT
[Unit]
Description=Nightly AUBOT backup
[Timer]
OnCalendar=*-*-* 16:00:00
Persistent=true
[Install]
WantedBy=timers.target
UNIT
sudo tee /etc/systemd/system/aubot-purge.service >/dev/null <<UNIT
[Unit]
Description=AUBOT retention purge (APP 11.2)
[Service]
Type=oneshot
WorkingDirectory=/opt/aubot
ExecStart=/usr/bin/docker compose -f deploy/aws/docker-compose.prod.yml --env-file .env.prod exec -T web python manage.py purge_expired
UNIT
sudo tee /etc/systemd/system/aubot-purge.timer >/dev/null <<UNIT
[Unit]
Description=Daily AUBOT retention purge
[Timer]
OnCalendar=*-*-* 17:00:00
Persistent=true
[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now aubot-backup.timer aubot-purge.timer'

echo "Waiting for https://$DOMAIN …"
for i in $(seq 1 60); do curl -fsS "https://$DOMAIN/api/health" >/dev/null 2>&1 && break; sleep 5; done
curl -fsS "https://$DOMAIN/api/health" && echo && echo "Live: https://$DOMAIN   Console: https://$DOMAIN/staff"
