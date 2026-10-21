#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups
file="backups/catalog-$(date -u +%Y%m%dT%H%M%SZ)-$$.dump"
./deploy/compose.sh exec -T db pg_dump -U catalog -d catalog -Fc > "$file.tmp"
mv "$file.tmp" "$file"
echo "$file"
