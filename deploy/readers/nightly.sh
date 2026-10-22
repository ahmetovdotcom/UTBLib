#!/bin/sh
# Persistent scheduler and online directory lookup. Does not modify AD or Platonus.
set -eu
cd "$(dirname "$0")/../.."
if [ "${READERS_LOCAL:-0}" = 1 ]; then
  set -- --env-file .env --env-file .env.readers -f compose.yaml -f compose.readers.yaml
  if [ -f compose.readers.local.json ]; then set -- "$@" -f compose.readers.local.json; fi
else
  set -- --env-file .env.server --env-file .env.readers -f compose.server.yaml -f compose.readers.yaml
fi
docker compose "$@" --profile readers-nightly --profile readers-tunnel up -d --build api platonus-readers-tunnel readers-scheduler
