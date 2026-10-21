#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
if [ -e .env.server ]; then
  echo '.env.server уже существует: пароли оставлены прежними.'
else
  command -v openssl >/dev/null
  db_secret=$(openssl rand -hex 24)
  import_secret=$(openssl rand -hex 32)
  admin_secret=$(openssl rand -hex 16)
  (set -C; cat > .env.server <<ENV
POSTGRES_PASSWORD=$db_secret
ADMIN_KEY=$import_secret
ADMIN_INITIAL_PASSWORD=$admin_secret
WEB_BIND=127.0.0.1
WEB_PORT=8097
COOKIE_SECURE=false
GOOGLE_BOOKS_API_KEY=
ENV
  )
  echo 'Создан .env.server. Логин admin, пароль — ADMIN_INITIAL_PASSWORD в этом файле.'
fi
if [ ! -e .env.marcsql ]; then cp .env.marcsql.example .env.marcsql; chmod 600 .env.marcsql; fi
echo 'Настройки готовы. Запуск: ./deploy/compose.sh up -d --build'
