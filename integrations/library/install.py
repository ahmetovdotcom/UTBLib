#!/usr/bin/env python3
"""Install the opt-in adapter without replacing existing library services/templates/env."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('library', type=Path)
parser.add_argument('--check', action='store_true', help='validate the installation without writing')
args = parser.parse_args()
root = args.library.resolve()
providers = root / 'bootstrap/providers.php'
if not providers.is_file() or not (root / 'app/Services/Library/CatalogReadService.php').is_file():
    parser.error('Expected the existing library Laravel project.')
line = '    App\\Integrations\\UTBLib\\CatalogServiceProvider::class,\n'
text = providers.read_text()
if line not in text:
    if text.count('];') != 1:
        parser.error('Unexpected bootstrap/providers.php structure; add CatalogServiceProvider manually.')
    text = text.replace('];', line + '];')
manifest = root / 'storage/app/utblib-catalog-adapter.json'
previous = json.loads(manifest.read_text()) if manifest.exists() else {}
digest = lambda data: hashlib.sha256(data).hexdigest()
files = []
# Only identifier selection changes; layout, CSS and the user's other edits stay intact.
replacements = {
    'resources/views/catalog.blade.php': [
        ("$detailIdentifier = $isbn !== '—' ? $isbn : (string) ($record['id'] ?? '');",
         "$detailIdentifier = ($record['source'] ?? '') === 'utblib' ? (string) $record['id'] : ($isbn !== '—' ? $isbn : (string) ($record['id'] ?? ''));"),
        ("detailUrl: detailHref(isbn !== '—' ? isbn : item?.id),",
         "detailUrl: detailHref(item?.source === 'utblib' ? item.id : (isbn !== '—' ? isbn : item?.id)),"),
        ("{{ e($isbn !== '—' ? $isbn : $detailHref) }}",
         "{{ e(($record['source'] ?? '') === 'utblib' ? $record['id'] : ($isbn !== '—' ? $isbn : $detailHref)) }}"),
        ("${escapeHtml(record.isbn !== '—' ? record.isbn : record.detailUrl)}",
         "${escapeHtml(item?.source === 'utblib' ? item.id : (record.isbn !== '—' ? record.isbn : record.detailUrl))}"),
    ],
    'resources/views/book.blade.php': [
        ("const identifier = (book?.isbn?.raw || book?.id || isbn);",
         "const identifier = book?.source === 'utblib' ? book.id : (book?.isbn?.raw || book?.id || isbn);"),
    ],
}
# Keep the original templates and route middleware; switch only the data producers.
controller = r"\App\Integrations\UTBLib\ContentController"
service = r"\App\Integrations\UTBLib\ContentService"
enabled = "config('utblib_catalog.content_enabled', false)"
route_changes = []
for kind in ('news', 'events'):
    opening = "Route::get('/" + kind + "/{slug}', function (Request $request, string $slug) use ($newsModelToPublicArticle) {"
    route_changes.append((opening, opening + "\n    if (" + enabled + ") return app(" + controller + "::class)->article($request, '" + kind + "', $slug);"))
opening = "Route::get('/news', function (Request $request) use ($newsModelToPublicArticle) {"
route_changes.append((opening, opening + "\n    if (" + enabled + ") return app(" + controller + "::class)->newsIndex($request);"))
opening = "    $events['items'] = [];"
route_changes.append((opening, opening + "\n    if (" + enabled + ") return app(" + controller + "::class)->eventsIndex($request, $events);"))
opening = "    return view('welcome', ["
route_changes.append((opening, "    if (" + enabled + ") {\n        $content = app(" + service + "::class);\n        $homepageNews = $content->all('news')->filter(fn ($r) => $r['data']['featured'])->take(6)->map(fn ($r) => $content->record($r));\n        $latestRepositoryWorks = $content->all('repository')->take(4)->map(fn ($r) => $content->record($r));\n    }\n\n" + opening))
route_changes.append(("Route::get('/resources/{slug}', PublicExternalResourceController::class)", "Route::get('/resources/{slug}', " + enabled + " ? [" + controller + "::class, 'resourceShow'] : PublicExternalResourceController::class)"))
route_changes.append(("Route::get('/resources/{externalResource}/open', ExternalResourceRedirectController::class)\n    ->whereNumber('externalResource')", "Route::get('/resources/{externalResource}/open', " + enabled + " ? [" + controller + "::class, 'resourceOpen'] : ExternalResourceRedirectController::class)\n    ->where('externalResource', " + enabled + " ? 'utblib-[0-9]+' : '[0-9]+')"))
for suffix, method in [('', 'index'), ('/{item}', 'show'), ('/{item}/download', 'download'), ('/{item}/view', 'view')]:
    opening = "Route::get('/repository" + suffix + "', [PublicRepositoryController::class, '" + method + "'])"
    before = opening + ("\n    ->whereNumber('item')" if suffix else '')
    after = "Route::get('/repository" + suffix + "', [" + enabled + " ? " + controller + "::class : PublicRepositoryController::class, '" + method + "'])" + ("\n    ->where('item', " + enabled + " ? 'utblib-[0-9]+' : '[0-9]+')" if suffix else '')
    route_changes.append((before, after))
replacements['routes/web.php'] = route_changes
replacements['app/Services/Library/PublicPortalStatistics.php'] = [(
    '    public function snapshot(): array\n    {',
    '    public function snapshot(): array\n    {\n        if (' + enabled + ') return app(' + service + '::class)->statistics();',
)]
replacements['resources/views/home/news.blade.php'] = [(
    "asset('storage/'.$item->cover_image)", "($item->source_system === 'utblib' ? $item->cover_image : asset('storage/'.$item->cover_image))",
)]
replacements['resources/views/news/show.blade.php'] = [(
    "route('news.registration-click',$article['id'])", "($article['registration_action'] ?? route('news.registration-click',$article['id']))",
)]

views = []
for relative, changes in replacements.items():
    target = root / relative
    content = target.read_text()
    for before, after in changes:
        if after in content:
            continue
        if content.count(before) != 1:
            parser.error(f'Unexpected template version, preserved: {relative}')
        content = content.replace(before, after)
    views.append((target, content))
base = Path(__file__).parent / 'files'
for source in sorted(base.rglob('*')):
    if not source.is_file():
        continue
    relative = source.relative_to(base)
    target = root / relative
    data = source.read_bytes()
    if target.exists() and target.read_bytes() != data and digest(target.read_bytes()) != previous.get(str(relative)):
        parser.error(f'Existing file changed independently, preserved: {relative}')
    files.append((relative, target, data))
if not args.check:
    for relative, target, data in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    providers.write_text(text)
    for target, content in views:
        target.write_text(content)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({str(r): digest(d) for r, _, d in files}, indent=2) + '\n')
print(('Checked' if args.check else 'Installed') + f' {len(files)} adapter files. Enable with UTBLIB_CATALOG_ENABLED=true and UTBLIB_CATALOG_URL.')
