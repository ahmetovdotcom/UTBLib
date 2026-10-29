<?php

namespace App\Integrations\UTBLib;

use Carbon\CarbonImmutable;
use Illuminate\Support\Collection;

class ContentService
{
    private array $loaded = [];
    public function __construct(private CatalogClient $client) {}

    public function all(string $kind): Collection
    {
        if (! isset($this->loaded[$kind])) {
            $items = collect(); $page = 1;
            do {
                $result = $this->client->get('content/'.$kind, ['page' => $page]);
                $items = $items->concat($result['data']);
            } while ($page++ < $result['meta']['last_page']);
            $this->loaded[$kind] = $items;
        }
        return $this->loaded[$kind];
    }

    public function find(string $kind, string $id): array
    {
        $result = $this->client->get('content/'.$kind.'/'.rawurlencode($id), [], true);
        abort_if($result === null, 404);
        return $result['data'];
    }

    public static function translated(array $translations, string $field, ?string $locale = null): string
    {
        foreach (array_unique([$locale ?: app()->getLocale(), 'kk', 'ru', 'en']) as $language) {
            $value = trim((string) ($translations[$language][$field] ?? ''));
            if ($value !== '') return $value;
        }
        return '';
    }

    public static function asset(array $row, string $slot): ?string
    {
        return empty($row['assets'][$slot]['url']) ? null : '/utblib-content/assets/'.$row['id'].'/'.$slot;
    }

    public function record(array $row): ContentRecord
    {
        $d = $row['data'];
        return new ContentRecord(array_merge($d, [
            'id' => 'utblib-'.$row['id'], 'slug' => $row['slug'], 'source_system' => 'utblib',
            'title' => self::translated($d['translations'], 'title'),
            'abstract' => self::translated($d['translations'], 'description'),
            'published_at' => CarbonImmutable::parse($row['published_at']), 'status' => 'published',
            'embargo_until' => empty($d['embargo_until']) ? null : CarbonImmutable::parse($d['embargo_until']),
            'file_name' => $row['assets']['pdf']['name'] ?? null,
            'file_size' => $row['assets']['pdf']['size'] ?? null,
            'file_url' => self::asset($row, 'pdf'), 'cover_image' => self::asset($row, 'image'),
            'type' => $row['kind'] === 'events' ? 'event' : ($d['news_type'] ?? 'announcement'),
        ]));
    }

    public function article(array $row): array
    {
        $d = $row['data']; $event = $row['kind'] === 'events';
        $published = CarbonImmutable::parse($row['published_at']);
        $start = empty($d['starts_at']) ? null : CarbonImmutable::parse($d['starts_at'])->timezone('Asia/Almaty');
        $end = empty($d['ends_at']) ? null : CarbonImmutable::parse($d['ends_at'])->timezone('Asia/Almaty');
        $titles = $excerpts = $bodies = $categories = [];
        foreach (['ru', 'kk', 'en'] as $lang) {
            $titles[$lang] = self::translated($d['translations'], 'title', $lang);
            $excerpts[$lang] = self::translated($d['translations'], 'description', $lang);
            $paragraphs = preg_split('/\R{2,}/u', self::translated($d['translations'], 'body', $lang), -1, PREG_SPLIT_NO_EMPTY);
            $bodies[$lang] = array_map(static fn ($p, $i) => ['type' => $i === 0 ? 'lead' : 'p', 'text' => $p], $paragraphs, array_keys($paragraphs));
            $categories[$lang] = trans('news.types.'.($event ? 'event' : ($d['news_type'] ?? 'announcement')), [], $lang);
        }
        return [
            'id' => 'utblib-'.$row['id'], 'slug' => $row['slug'], 'topic' => $event ? 'events' : 'research',
            'featured' => $d['featured'], 'language' => app()->getLocale(),
            'published_at' => $published->toDateString(),
            'published_display' => ['ru' => $published->format('d.m.Y'), 'kk' => $published->format('d.m.Y'), 'en' => $published->format('F j, Y')],
            'title' => $titles, 'excerpt' => $excerpts, 'category' => $categories,
            'hero' => ['image' => self::asset($row, 'image'), 'alt' => $titles], 'body' => $bodies,
            'cta' => null, 'repository' => null, 'schema_type' => $event ? 'Event' : 'NewsArticle',
            'registration_action' => '/utblib-content/events/utblib-'.$row['id'].'/register',
            'event' => ['starts_at' => $start?->toIso8601String(), 'ends_at' => $end?->toIso8601String(),
                'starts_display' => $start?->translatedFormat('d F Y, H:i'), 'ends_display' => $end?->translatedFormat('d F Y, H:i'),
                'venue' => self::translated($d['translations'], 'venue'), 'online_url' => $d['online_url'],
                'registration_url' => $event ? $d['registration_url'] : '', 'registration_required' => $event && ! empty($d['registration_url']),
                'organizer' => $d['organizer'], 'contact_name' => null],
        ];
    }

    public function statistics(): array
    {
        $catalog = $this->client->get('catalog', ['limit' => 1]);
        return ['catalog_titles' => $catalog['meta']['total'], 'physical_copies' => $catalog['meta']['total_copies'],
            'electronic_materials' => null, 'published_resources' => $this->all('resources')->count(),
            'published_repository' => $this->all('repository')->count(), 'published_news' => $this->all('news')->count(),
            'published_events' => $this->all('events')->filter(fn ($r) => $this->upcoming($r))->count()];
    }

    public function upcoming(array $row): bool
    {
        $end = $row['data']['ends_at'] ?: $row['data']['starts_at'];
        return $end && CarbonImmutable::parse($end)->greaterThanOrEqualTo(now());
    }
}
