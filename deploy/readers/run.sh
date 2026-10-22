#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
run_source() {
  docker compose --env-file .env.server --env-file .env.readers \
    -f compose.server.yaml -f compose.readers.yaml run --rm --no-deps readers-sync \
    python -m app.reader_sync "$@"
}
# Same order as the reference project. Stop if a source fails, so a broken
# AD scan cannot be followed by a fresh Platonus import with no AD identities.
if [ "${1:-}" = all ]; then
  shift
  # Only shared options: personal-data sync does not implement year/photos/missing.
  for arg in "$@"; do
    case "$arg" in
      --dry-run) ;;
      *) echo 'Для all поддерживается только --dry-run. Другие параметры задавайте отдельным источникам.' >&2; exit 2 ;;
    esac
  done
  run_source active_directory "$@"
  run_source platonus "$@"
  run_source platonus-personal "$@"
else
  run_source "$@"
fi
