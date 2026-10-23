#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
folder="backups/$stamp"
mkdir -p "$folder"
# Uploads are immutable; copy them after DB snapshot so every referenced file is included.
docker compose exec -T db pg_dump -U support -d support -Fc > "$folder/database.dump"
docker compose exec -T api tar -C /data/uploads -czf - . > "$folder/uploads.tar.gz"
cp .env "$folder/config.env"
printf '%s\n' "备份完成：$folder（包含密钥，请加密离线保存）"
