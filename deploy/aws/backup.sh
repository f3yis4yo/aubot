#!/bin/bash
# Nightly PostgreSQL dump to S3 (bucket kept for 30 days by lifecycle rule). Installed as a systemd timer.
set -euo pipefail
cd /opt/aubot
BUCKET=$(grep '^BACKUP_BUCKET=' .env.prod | cut -d= -f2)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -f deploy/aws/docker-compose.prod.yml --env-file .env.prod exec -T db pg_dump -U aubot -Fc aubot \
  | aws s3 cp - "s3://${BUCKET}/db/aubot-${STAMP}.dump" --sse AES256
