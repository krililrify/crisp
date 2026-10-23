#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
folder=${1:?Usage: scripts/restore.sh backups/TIMESTAMP}
[ -f "$folder/database.dump" ] && [ -f "$folder/uploads.tar.gz" ] && [ -f "$folder/config.env" ]
printf '此操作覆盖当前数据库、上传文件和密钥。输入 RESTORE 继续：'
read -r answer
[ "$answer" = RESTORE ] || exit 1
docker compose stop api worker migrate
cp "$folder/config.env" .env
chmod 600 .env
docker compose up -d db
docker compose exec -T db pg_restore -U support -d support --clean --if-exists --no-owner < "$folder/database.dump"
docker compose run --rm --no-deps -T --user 10001 api sh -c 'find /data/uploads -type f -delete; tar -C /data/uploads -xzf -' < "$folder/uploads.tar.gz"
docker compose up -d --force-recreate migrate api worker
printf '%s\n' '恢复完成；请检查健康状态和 Telegram/Bark 连接。'
