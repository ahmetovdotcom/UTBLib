#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "${1:-}" != '--apply' ]; then
  echo 'Импорт каталога и экземпляров из MARCSQL (источник только SELECT).'
  echo 'Запуск: ./deploy/import-all.sh --apply'
  exit 2
fi
# Resolve actual IDs in this installation, never assume IDs 1/2/6/7.
IMPORT_TYPE_MAP=$(./deploy/compose.sh exec -T api python -m app.prepare_server_import)
export IMPORT_TYPE_MAP
./deploy/compose.sh build importer
exec ./deploy/compose.sh run --rm --no-deps importer python -m app.import_marcsql_all --apply
