#!/usr/bin/env bash
# Run on the existing production host AFTER pulling main (UTBLib) and audit (library).
# Preserves the actual Compose files, volumes, readers overlays and proxy network.
set -Eeuo pipefail
umask 077
utb_dir=$(cd "$(dirname "$0")/.." && pwd)
library_dir=$(cd "${1:?Usage: bash deploy/activate-student-frontend.sh /home/admtutor/projects/library}" && pwd)
cd "$utb_dir"
phase=preflight
trap 'echo "Stopped during: $phase. Do not clear databases or volumes. Fix the error before continuing." >&2' ERR

uc() {
  docker compose -p kaztbu-catalog-v2 --project-directory "$utb_dir" \
    --env-file "$utb_dir/.env.server" --env-file "$utb_dir/.env.readers" \
    -f "$utb_dir/compose.server.yaml" -f "$utb_dir/compose.readers.yaml" \
    -f "$utb_dir/compose.circulation.yaml" --profile readers-nightly --profile readers-tunnel "$@"
}
lc() {
  docker compose -p library --project-directory "$library_dir" \
    --env-file "$library_dir/.env" -f "$library_dir/docker-compose.yml" "$@"
}

test "$(git -C "$utb_dir" branch --show-current)" = main
test "$(git -C "$library_dir" branch --show-current)" = audit
test -f "$library_dir/scripts/export-utblib-public-content.php"
test -s .env.server && test -s .env.readers
python3 deploy/configure-student-frontend.py --library "$library_dir"
uc config --quiet
lc config --quiet
lc config --format json | python3 deploy/check-staff-proxy.py --library "$library_dir"
# This alias and network already exist on the target host; fail rather than alter networking.
lc exec -T app curl -fsS --max-time 10 http://utblib-web/api/health </dev/null

phase=backup
release_dir=$(mktemp -d "$(dirname "$utb_dir")/frontend-release-$(date -u +%Y%m%dT%H%M%S)-XXXXXX")
chmod 700 "$release_dir"
echo "Release backups: $release_dir"
git -C "$utb_dir" rev-parse HEAD > "$release_dir/utblib-commit.txt"
git -C "$library_dir" rev-parse HEAD > "$release_dir/library-commit.txt"
cp .env.server "$release_dir/utblib.env"
cp compose.server.yaml "$release_dir/utblib-compose.yaml"
cp "$library_dir/.env" "$release_dir/library.env"
cp "$library_dir/docker-compose.yml" "$release_dir/library-compose.yml"
if [ -d "$library_dir/public/build" ]; then
  tar -czf "$release_dir/library-assets-before.tar.gz" -C "$library_dir/public" build
fi
uc exec -T db pg_dump -U catalog -d catalog -Fc > "$release_dir/utblib.dump"
uc exec -T db pg_restore --list < "$release_dir/utblib.dump" > /dev/null
# The live application uses a recovered DB, which can differ from POSTGRES_DB.
library_database=$(lc exec -T app php -r 'require "vendor/autoload.php"; $app=require "bootstrap/app.php"; $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap(); echo config("database.connections.".config("database.default").".database");' </dev/null)
[[ "$library_database" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
printf '%s\n' "$library_database" > "$release_dir/library-database.txt"
lc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$1" -Fc' sh "$library_database" > "$release_dir/library.dump"
lc exec -T postgres pg_restore --list < "$release_dir/library.dump" > /dev/null

phase=export-publications
lc exec -T app php scripts/export-utblib-public-content.php > "$release_dir/public-content.json"

phase=build
# Build assets with supported Node, isolated from .env and uploads. Host Node 18 is too old.
mkdir "$release_dir/library-source"
git -C "$library_dir" archive HEAD | tar -x -C "$release_dir/library-source"
docker run --rm -v "$release_dir/library-source:/app" -w /app node:22-bookworm-slim \
  sh -ec 'npm ci --no-audit --no-fund && npm run build'
uc build api web readers-scheduler circulation-worker
lc build app

phase=validate-publications
# The new image validates every publication before any data changes or app restart.
uc run --rm -T --no-deps api python -m app.import_library_content < "$release_dir/public-content.json"

phase=configure
python3 deploy/configure-student-frontend.py --library "$library_dir" --apply

phase=update-utblib
uc up -d --no-build --wait api web readers-scheduler platonus-readers-tunnel circulation-worker
uc exec -T api python -m app.import_library_content --apply < "$release_dir/public-content.json"

phase=update-library
# Keep old hashed assets available to already-open browsers; replace manifest last.
docker run --rm --network none -v "$release_dir/library-source/public/build:/built:ro" \
  -v "$library_dir/public:/public" node:22-bookworm-slim sh -ec \
  'mkdir -p /public/build/assets; cp -a /built/assets/. /public/build/assets/; cp /built/manifest.json /public/build/manifest.json.new; chmod -R a+rX /public/build; mv /public/build/manifest.json.new /public/build/manifest.json'
lc up -d --no-build --no-deps --wait app
# Refresh cached homepage blocks after the publication transfer. Does not clear sessions.
lc exec -T --user www-data app php artisan cache:clear </dev/null

phase=verify
curl -fsS --retry 5 --retry-connrefused --retry-delay 2 http://127.0.0.1:8097/api/health
lc exec -T app curl -fsS --max-time 10 http://utblib-web/api/health </dev/null
lc exec -T app curl -fsS --max-time 15 \
  --resolve elibrary.kaztbu.edu.kz:443:127.0.0.1 https://elibrary.kaztbu.edu.kz/login -o /dev/null </dev/null
staff_page=$(lc exec -T app curl -fsS --max-time 15 http://utblib-web/ </dev/null)
staff_https_page=$(lc exec -T app curl -fsS --max-time 15 \
  --resolve libstaff.kaztbu.edu.kz:443:127.0.0.1 https://libstaff.kaztbu.edu.kz/ </dev/null)
if [ -z "$staff_page" ] || [ "$staff_page" != "$staff_https_page" ]; then
  echo 'Staff domain does not serve the UTBLib frontend. Check the libstaff nginx configuration.' >&2
  exit 1
fi
lc exec -T app curl -fsS --max-time 15 \
  --resolve libstaff.kaztbu.edu.kz:443:127.0.0.1 https://libstaff.kaztbu.edu.kz/api/health </dev/null
echo 'Staff HTTPS routing: OK'
lc exec -T --user www-data app php scripts/check-utblib-frontend.php </dev/null
# Only this run's disposable Git archive and npm packages; backups stay intact.
docker run --rm --network none -v "$release_dir/library-source:/build" node:22-bookworm-slim \
  sh -ec 'find /build -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
rmdir "$release_dir/library-source"
echo
echo "Frontend update complete. Backups: $release_dir"
echo 'Now verify a real student AD login at https://elibrary.kaztbu.edu.kz/login'
