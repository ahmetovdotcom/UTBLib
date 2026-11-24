#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <UTBLib API container> <UTBLib username with site.manage>" >&2
    exit 64
fi

container="$1"
username="$2"
directory="$(cd "$(dirname "$0")" && pwd)"
staging="$(docker exec "$container" mktemp -d /tmp/utblib-interlibrary.XXXXXXXX)"
case "$staging" in
    /tmp/utblib-interlibrary.????????) ;;
    *) echo "Unexpected staging path" >&2; exit 1 ;;
esac
trap 'docker exec "$container" rm -rf -- "$staging"' EXIT

docker cp "$directory/interlibrary/." "$container:$staging/"
docker exec -w /app -e PYTHONPATH=/app "$container" \
    python "$staging/import_resources.py" "$username"
