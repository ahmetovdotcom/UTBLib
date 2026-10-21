#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec docker compose -p kaztbu-catalog-v2 --env-file .env.server -f compose.server.yaml "$@"
