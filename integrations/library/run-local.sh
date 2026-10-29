#!/bin/sh
# Preview the existing library frontend, with its catalogue supplied by local UTBLib.
set -eu
if [ "$#" -ne 1 ]; then
  echo 'Usage: sh integrations/library/run-local.sh /path/to/library' >&2
  exit 2
fi
cd "$1"
test -f artisan
UTBLIB_CATALOG_ENABLED=true \
UTBLIB_CONTENT_ENABLED=true \
UTBLIB_CATALOG_URL="${UTBLIB_CATALOG_URL:-http://127.0.0.1:8096}" \
APP_URL="http://127.0.0.1:${LIBRARY_PREVIEW_PORT:-8098}" \
SESSION_DRIVER=file CACHE_STORE=array \
php artisan serve --host=127.0.0.1 --port="${LIBRARY_PREVIEW_PORT:-8098}" --no-reload
